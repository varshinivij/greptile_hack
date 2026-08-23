"""Offline-v1 gate coordination and decision assembly."""

from __future__ import annotations

from collections import Counter

from .completeness import evaluate_completeness
from .gates import (
    evaluate_efficiency_and_objective,
    evaluate_evidence_validity,
    evaluate_quality,
    evaluate_reliability,
    evaluate_safety,
)
from .models import (
    DecisionAction,
    DecisionReport,
    EvaluationEvidence,
    GateName,
    GateResult,
    GateStatus,
    PolicyConfig,
    ReasonCode,
    RolloutStage,
)
from .parsing import parse_evidence, parse_policy_config
from .validation import validate_policy_inputs


GATE_ORDER = (
    GateName.EVIDENCE_VALIDITY,
    GateName.SAFETY,
    GateName.EVIDENCE_COMPLETENESS,
    GateName.RELIABILITY,
    GateName.QUALITY,
    GateName.EFFICIENCY_AND_OBJECTIVE,
)


def evaluate_policy(
    evidence: EvaluationEvidence, config: PolicyConfig
) -> DecisionReport:
    """Evaluate normalized evidence without performing I/O or mutating rollout state."""
    validate_policy_inputs(evidence, config)

    validity = evaluate_evidence_validity(evidence, config)
    safety = evaluate_safety(evidence, config)
    gate_results = [validity, safety]

    if safety.status is GateStatus.FAILED:
        return _build_report(
            evidence,
            config,
            DecisionAction.REJECT,
            _with_not_evaluated(gate_results),
            safety,
        )
    if validity.status is GateStatus.HELD:
        return _build_report(
            evidence,
            config,
            DecisionAction.HOLD,
            _with_not_evaluated(gate_results),
            validity,
        )

    completeness = evaluate_completeness(evidence, config)
    gate_results.append(completeness)
    if completeness.status is GateStatus.HELD:
        return _build_report(
            evidence,
            config,
            DecisionAction.HOLD,
            _with_not_evaluated(gate_results),
            completeness,
        )

    reliability = evaluate_reliability(evidence, config)
    quality = evaluate_quality(evidence, config)
    efficiency = evaluate_efficiency_and_objective(evidence, config)
    gate_results.extend((reliability, quality, efficiency))

    held_gate = _first_with_status(gate_results, GateStatus.HELD)
    if held_gate:
        return _build_report(
            evidence, config, DecisionAction.HOLD, tuple(gate_results), held_gate
        )

    failed_gate = _first_with_status(gate_results, GateStatus.FAILED)
    if failed_gate:
        return _build_report(
            evidence, config, DecisionAction.REJECT, tuple(gate_results), failed_gate
        )

    review_gate = _first_with_status(gate_results, GateStatus.REVIEW)
    if review_gate:
        return _build_report(
            evidence,
            config,
            DecisionAction.HUMAN_REVIEW,
            tuple(gate_results),
            review_gate,
        )

    return _build_report(
        evidence,
        config,
        DecisionAction.PROMOTE,
        tuple(gate_results),
        gate_results[-1],
    )


def evaluate_policy_payload(
    evidence_payload: object, config_payload: object
) -> DecisionReport:
    """Parse external payloads and evaluate them through the versioned contract boundary."""
    return evaluate_policy(
        parse_evidence(evidence_payload), parse_policy_config(config_payload)
    )


def _build_report(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
    action: DecisionAction,
    gate_results: tuple[GateResult, ...],
    decisive_gate: GateResult,
) -> DecisionReport:
    if action is DecisionAction.PROMOTE:
        reason_codes = (ReasonCode.ALL_GATES_PASSED,)
        summary = "Candidate passed all offline policy gates and is eligible for shadow traffic."
    else:
        reason_codes = _collect_reason_codes(gate_results)
        summary = f"{_action_label(action)}: {decisive_gate.summary}"

    missing_evidence = tuple(
        sorted({missing for gate in gate_results for missing in gate.missing_evidence})
    )
    segment_counts = Counter(pair.segment for pair in evidence.pairs)
    return DecisionReport(
        action=action,
        current_stage=evidence.stage,
        next_stage=RolloutStage.SHADOW if action is DecisionAction.PROMOTE else None,
        evidence_schema_version=evidence.schema_version,
        policy_id=config.policy_id,
        policy_version=config.policy_version,
        baseline_version=evidence.baseline_version,
        candidate_version=evidence.candidate_version,
        reason_codes=reason_codes,
        summary=summary,
        gate_results=gate_results,
        paired_sample_count=len(evidence.pairs),
        segment_counts=tuple(sorted(segment_counts.items())),
        missing_evidence=missing_evidence,
    )


def _with_not_evaluated(results: list[GateResult]) -> tuple[GateResult, ...]:
    evaluated_names = {result.name for result in results}
    completed = list(results)
    for gate_name in GATE_ORDER:
        if gate_name in evaluated_names:
            continue
        completed.append(
            GateResult(
                name=gate_name,
                status=GateStatus.NOT_EVALUATED,
                reason_codes=(),
                summary="Not evaluated because an earlier gate determined the decision.",
            )
        )
    return tuple(completed)


def _first_with_status(
    results: list[GateResult], status: GateStatus
) -> GateResult | None:
    for result in results:
        if result.status is status:
            return result
    return None


def _collect_reason_codes(results: tuple[GateResult, ...]) -> tuple[ReasonCode, ...]:
    reasons: list[ReasonCode] = []
    for result in results:
        for reason in result.reason_codes:
            if reason not in reasons:
                reasons.append(reason)
    return tuple(reasons)


def _action_label(action: DecisionAction) -> str:
    labels = {
        DecisionAction.HOLD: "Candidate held",
        DecisionAction.REJECT: "Candidate rejected",
        DecisionAction.HUMAN_REVIEW: "Candidate requires human review",
        DecisionAction.ROLLBACK: "Candidate requires rollback",
    }
    return labels[action]
