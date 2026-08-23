"""Evidence completeness and sufficiency gate."""

from __future__ import annotations

from collections import Counter

from .calculations import (
    both_succeeded,
    pair_has_completed_evaluator,
    required_evaluators,
    rounded,
)
from .models import (
    DeterministicResult,
    EvaluationEvidence,
    EvaluatorName,
    EvaluatorStatus,
    ExecutionStatus,
    GateName,
    GateResult,
    GateStatus,
    MetricName,
    ObjectiveMetric,
    Observation,
    OutputType,
    PolicyConfig,
    ReasonCode,
)


def evaluate_completeness(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
) -> GateResult:
    observations, missing_segments = _coverage_observations(evidence, config)
    missing: set[str] = set()
    if config.require_objective and evidence.objective is None:
        missing.add("objective")

    required_metrics = _required_metrics(evidence, config)
    pair_missing, completed_pair_counts = _inspect_pairs(
        evidence,
        config,
        required_metrics,
    )
    missing.update(pair_missing)
    missing.update(
        _missing_completed_evaluators(evidence, config, completed_pair_counts)
    )
    reasons = _sufficiency_reasons(evidence, config, missing_segments, missing)

    if reasons:
        return GateResult(
            name=GateName.EVIDENCE_COMPLETENESS,
            status=GateStatus.HELD,
            reason_codes=tuple(reasons),
            summary=(
                "Required evaluator evidence, samples, segment coverage, "
                "or observation time is incomplete."
            ),
            observations=tuple(observations),
            missing_evidence=tuple(sorted(missing)),
        )
    return GateResult(
        name=GateName.EVIDENCE_COMPLETENESS,
        status=GateStatus.PASSED,
        reason_codes=(),
        summary="Required evidence, samples, segments, and observation time are complete.",
        observations=tuple(observations),
    )


def _coverage_observations(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
) -> tuple[list[Observation], tuple[str, ...]]:
    observations = [
        Observation(
            metric="paired_samples",
            observed=len(evidence.pairs),
            threshold=config.minimum_paired_samples,
        ),
        Observation(
            metric="observation_duration_seconds",
            observed=rounded(evidence.observation_duration_seconds),
            threshold=rounded(config.minimum_observation_duration_seconds),
        ),
    ]
    segment_counts = Counter(pair.segment for pair in evidence.pairs)
    missing_segments: list[str] = []
    for segment in config.required_segments:
        count = segment_counts[segment]
        observations.append(
            Observation(
                metric=f"segment.{segment}.paired_samples",
                observed=count,
                threshold=config.minimum_pairs_per_segment,
            )
        )
        if count < config.minimum_pairs_per_segment:
            missing_segments.append(segment)
    return observations, tuple(missing_segments)


def _required_metrics(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
) -> set[MetricName]:
    metrics = {guardrail.metric for guardrail in config.efficiency_guardrails}
    if (
        evidence.objective
        and evidence.objective.metric is not ObjectiveMetric.QUALITY_PASS_RATE
    ):
        metrics.add(MetricName(evidence.objective.metric.value))
    return metrics


def _inspect_pairs(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
    required_metrics: set[MetricName],
) -> tuple[set[str], Counter[tuple[OutputType, EvaluatorName]]]:
    missing: set[str] = set()
    completed_pair_counts: Counter[tuple[OutputType, EvaluatorName]] = Counter()
    for pair in evidence.pairs:
        evaluators = required_evaluators(config, pair.output_type)
        attempts = (("baseline", pair.baseline), ("candidate", pair.candidate))
        for role, attempt in attempts:
            path = f"pairs.{pair.pair_id}.{role}"
            if attempt.execution_status is ExecutionStatus.INFRASTRUCTURE_ERROR:
                missing.add(f"{path}.execution")
                continue
            if attempt.execution_status is not ExecutionStatus.SUCCESS:
                continue
            if (
                EvaluatorName.DETERMINISTIC in evaluators
                and attempt.deterministic_result
                not in (DeterministicResult.PASSED, DeterministicResult.FAILED)
            ):
                missing.add(f"{path}.deterministic")
            if (
                EvaluatorName.GREPTILE in evaluators
                and attempt.greptile.status is not EvaluatorStatus.COMPLETED
            ):
                missing.add(f"{path}.greptile")

        if both_succeeded(pair):
            for evaluator in evaluators:
                if pair_has_completed_evaluator(pair, evaluator):
                    completed_pair_counts[(pair.output_type, evaluator)] += 1
            for role, attempt in attempts:
                for metric in required_metrics:
                    if attempt.metrics.value(metric) is None:
                        missing.add(
                            f"pairs.{pair.pair_id}.{role}.metrics.{metric.value}"
                        )
    return missing, completed_pair_counts


def _missing_completed_evaluators(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
    completed_pair_counts: Counter[tuple[OutputType, EvaluatorName]],
) -> set[str]:
    missing: set[str] = set()
    present_output_types = {pair.output_type for pair in evidence.pairs}
    for requirement in config.required_evaluators:
        if requirement.output_type not in present_output_types:
            continue
        for evaluator in requirement.evaluators:
            if completed_pair_counts[(requirement.output_type, evaluator)] == 0:
                missing.add(
                    f"completed_pairs.{requirement.output_type.value}.{evaluator.value}"
                )
    return missing


def _sufficiency_reasons(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
    missing_segments: tuple[str, ...],
    missing: set[str],
) -> list[ReasonCode]:
    reasons: list[ReasonCode] = []
    if len(evidence.pairs) < config.minimum_paired_samples:
        reasons.append(ReasonCode.SAMPLE_TOO_SMALL)
        missing.add("paired_samples")
    if missing_segments:
        reasons.append(ReasonCode.SEGMENT_COVERAGE_MISSING)
        missing.update(f"segments.{segment}" for segment in missing_segments)
    if (
        evidence.observation_duration_seconds
        < config.minimum_observation_duration_seconds
    ):
        reasons.append(ReasonCode.OBSERVATION_WINDOW_TOO_SHORT)
        missing.add("observation_duration_seconds")
    if missing:
        reasons.insert(0, ReasonCode.EVIDENCE_INCOMPLETE)
    return reasons
