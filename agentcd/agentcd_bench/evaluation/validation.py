"""Cross-field validation for typed policy inputs."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .models import (
    EVIDENCE_SCHEMA_VERSION,
    OFFLINE_POLICY_VERSION,
    POLICY_CONFIG_SCHEMA_VERSION,
    AttemptEvidence,
    ContractError,
    EvaluationEvidence,
    EvaluatorStatus,
    PolicyConfig,
    RolloutStage,
)


def validate_policy_inputs(evidence: EvaluationEvidence, config: PolicyConfig) -> None:
    if evidence.schema_version != EVIDENCE_SCHEMA_VERSION:
        raise ContractError(
            f"unsupported evidence schema version: {evidence.schema_version}"
        )
    if config.schema_version != POLICY_CONFIG_SCHEMA_VERSION:
        raise ContractError(
            f"unsupported policy config schema version: {config.schema_version}"
        )
    if config.policy_version != OFFLINE_POLICY_VERSION:
        raise ContractError(f"unsupported policy version: {config.policy_version}")
    if config.evidence_schema_version != evidence.schema_version:
        raise ContractError(
            "policy_config.evidence_schema_version does not match evidence.schema_version"
        )
    if config.supported_stage is not RolloutStage.OFFLINE:
        raise ContractError("policy v1 supports only the offline rollout stage")
    if evidence.stage is not config.supported_stage:
        raise ContractError(
            "evidence.stage does not match policy_config.supported_stage"
        )

    _require_non_empty(config.policy_id, "policy_config.policy_id")
    _require_non_empty(config.policy_version, "policy_config.policy_version")
    _require_non_empty(evidence.baseline_version, "evidence.baseline_version")
    _require_non_empty(evidence.candidate_version, "evidence.candidate_version")
    _require_non_empty(evidence.suite_version, "evidence.suite_version")
    _require_finite_non_negative(
        evidence.observation_duration_seconds, "evidence.observation_duration_seconds"
    )

    if config.minimum_paired_samples < 1:
        raise ContractError("policy_config.minimum_paired_samples must be at least 1")
    if config.minimum_pairs_per_segment < 1:
        raise ContractError(
            "policy_config.minimum_pairs_per_segment must be at least 1"
        )
    _require_finite_non_negative(
        config.minimum_observation_duration_seconds,
        "policy_config.minimum_observation_duration_seconds",
    )
    _require_rate(
        config.maximum_candidate_failure_rate,
        "policy_config.maximum_candidate_failure_rate",
    )
    _require_rate(
        config.maximum_failure_rate_regression,
        "policy_config.maximum_failure_rate_regression",
    )
    _require_rate(
        config.quality_non_inferiority_margin,
        "policy_config.quality_non_inferiority_margin",
    )
    _require_rate(
        config.minimum_objective_improvement,
        "policy_config.minimum_objective_improvement",
    )

    _reject_duplicates(config.required_segments, "policy_config.required_segments")
    if not config.required_segments:
        raise ContractError("policy_config.required_segments must not be empty")
    _reject_duplicates(
        config.critical_finding_severities, "policy_config.critical_finding_severities"
    )
    _reject_duplicates(
        config.forbidden_policy_violations, "policy_config.forbidden_policy_violations"
    )
    for index, segment in enumerate(config.required_segments):
        _require_non_empty(segment, f"policy_config.required_segments[{index}]")
    for index, violation in enumerate(config.forbidden_policy_violations):
        _require_non_empty(
            violation, f"policy_config.forbidden_policy_violations[{index}]"
        )

    requirement_types = tuple(
        requirement.output_type for requirement in config.required_evaluators
    )
    if not config.required_evaluators:
        raise ContractError("policy_config.required_evaluators must not be empty")
    _reject_duplicates(
        requirement_types, "policy_config.required_evaluators.output_type"
    )
    for index, requirement in enumerate(config.required_evaluators):
        if not requirement.evaluators:
            raise ContractError(
                f"policy_config.required_evaluators[{index}].evaluators must not be empty"
            )
        _reject_duplicates(
            requirement.evaluators,
            f"policy_config.required_evaluators[{index}].evaluators",
        )

    finding_limit_severities = tuple(
        limit.severity for limit in config.finding_delta_limits
    )
    _reject_duplicates(
        finding_limit_severities, "policy_config.finding_delta_limits.severity"
    )
    for index, limit in enumerate(config.finding_delta_limits):
        if limit.maximum_candidate_delta < 0:
            raise ContractError(
                f"policy_config.finding_delta_limits[{index}].maximum_candidate_delta must be non-negative"
            )

    guardrail_metrics = tuple(
        guardrail.metric for guardrail in config.efficiency_guardrails
    )
    _reject_duplicates(guardrail_metrics, "policy_config.efficiency_guardrails.metric")
    for index, guardrail in enumerate(config.efficiency_guardrails):
        _require_finite_non_negative(
            guardrail.maximum_candidate_to_baseline_ratio,
            f"policy_config.efficiency_guardrails[{index}].maximum_candidate_to_baseline_ratio",
        )

    pair_ids = tuple(pair.pair_id for pair in evidence.pairs)
    _reject_duplicates(pair_ids, "evidence.pairs.pair_id")
    attempt_ids: list[str] = []
    configured_output_types = set(requirement_types)
    for index, pair in enumerate(evidence.pairs):
        path = f"evidence.pairs[{index}]"
        _require_non_empty(pair.pair_id, f"{path}.pair_id")
        _require_non_empty(pair.task_id, f"{path}.task_id")
        _require_non_empty(pair.segment, f"{path}.segment")
        if pair.output_type not in configured_output_types:
            raise ContractError(
                f"{path}.output_type has no evaluator requirement in policy config"
            )
        _validate_attempt(pair.baseline, f"{path}.baseline")
        _validate_attempt(pair.candidate, f"{path}.candidate")
        attempt_ids.extend((pair.baseline.attempt_id, pair.candidate.attempt_id))
    _reject_duplicates(attempt_ids, "evidence.pairs.attempt_id")


def _validate_attempt(attempt: AttemptEvidence, path: str) -> None:
    _require_non_empty(attempt.attempt_id, f"{path}.attempt_id")
    _require_non_empty(attempt.source_revision, f"{path}.source_revision")
    _require_non_empty(attempt.prompt_hash, f"{path}.prompt_hash")
    _require_non_empty(attempt.model, f"{path}.model")
    _require_non_empty(attempt.runner, f"{path}.runner")
    _require_non_empty(attempt.tool_policy, f"{path}.tool_policy")
    _reject_duplicates(attempt.policy_violations, f"{path}.policy_violations")
    for index, violation in enumerate(attempt.policy_violations):
        _require_non_empty(violation, f"{path}.policy_violations[{index}]")

    metrics = attempt.metrics
    for name, value in (
        ("duration_ms", metrics.duration_ms),
        ("total_tokens", metrics.total_tokens),
        ("tool_call_count", metrics.tool_call_count),
        ("estimated_cost_usd", metrics.estimated_cost_usd),
    ):
        if value is not None:
            _require_finite_non_negative(value, f"{path}.metrics.{name}")

    if (
        attempt.greptile.status is not EvaluatorStatus.COMPLETED
        and attempt.greptile.findings
    ):
        raise ContractError(
            f"{path}.greptile.findings must be empty unless status is completed"
        )
    finding_ids = tuple(finding.finding_id for finding in attempt.greptile.findings)
    _reject_duplicates(finding_ids, f"{path}.greptile.findings.finding_id")
    for index, finding in enumerate(attempt.greptile.findings):
        finding_path = f"{path}.greptile.findings[{index}]"
        _require_non_empty(finding.finding_id, f"{finding_path}.finding_id")
        _require_non_empty(finding.category, f"{finding_path}.category")
        if finding.file_path is not None:
            _require_non_empty(finding.file_path, f"{finding_path}.file_path")


def _reject_duplicates(values: Iterable[object], path: str) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise ContractError(f"{path} contains duplicate value: {value}")
        seen.add(value)


def _require_non_empty(value: str, path: str) -> None:
    if not value.strip():
        raise ContractError(f"{path} must be a non-empty string")


def _require_finite_non_negative(value: float, path: str) -> None:
    if value < 0 or not math.isfinite(value):
        raise ContractError(f"{path} must be a finite non-negative number")


def _require_rate(value: float, path: str) -> None:
    _require_finite_non_negative(value, path)
    if value > 1:
        raise ContractError(f"{path} must be between 0 and 1")
