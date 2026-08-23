"""Strict parsing for JSON-shaped evaluation contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from .models import (
    AttemptEvidence,
    AttemptMetrics,
    ContractError,
    DeterministicResult,
    EvaluationEvidence,
    EvaluatorName,
    EvaluatorRequirement,
    EvaluatorStatus,
    ExecutionStatus,
    FindingDeltaLimit,
    FindingSeverity,
    GreptileEvidence,
    GreptileFinding,
    MetricGuardrail,
    MetricName,
    Objective,
    ObjectiveMetric,
    OutputType,
    PairedEvidence,
    PolicyConfig,
    RolloutStage,
)


EnumValue = TypeVar("EnumValue", bound=StrEnum)


def parse_evidence(payload: object) -> EvaluationEvidence:
    data = _mapping(payload, "evidence")
    pairs = tuple(
        _parse_pair(item, f"evidence.pairs[{index}]")
        for index, item in enumerate(
            _sequence(_field(data, "pairs", "evidence"), "evidence.pairs")
        )
    )
    objective_value = data.get("objective")
    objective = (
        None
        if objective_value is None
        else _parse_objective(objective_value, "evidence.objective")
    )
    return EvaluationEvidence(
        schema_version=_non_empty_string(
            _field(data, "schema_version", "evidence"), "evidence.schema_version"
        ),
        baseline_version=_non_empty_string(
            _field(data, "baseline_version", "evidence"), "evidence.baseline_version"
        ),
        candidate_version=_non_empty_string(
            _field(data, "candidate_version", "evidence"), "evidence.candidate_version"
        ),
        stage=_enum(RolloutStage, _field(data, "stage", "evidence"), "evidence.stage"),
        suite_version=_non_empty_string(
            _field(data, "suite_version", "evidence"), "evidence.suite_version"
        ),
        observation_duration_seconds=_non_negative_number(
            _field(data, "observation_duration_seconds", "evidence"),
            "evidence.observation_duration_seconds",
        ),
        objective=objective,
        pairs=pairs,
    )


def parse_policy_config(payload: object) -> PolicyConfig:
    data = _mapping(payload, "policy_config")
    return PolicyConfig(
        schema_version=_non_empty_string(
            _field(data, "schema_version", "policy_config"),
            "policy_config.schema_version",
        ),
        policy_id=_non_empty_string(
            _field(data, "policy_id", "policy_config"), "policy_config.policy_id"
        ),
        policy_version=_non_empty_string(
            _field(data, "policy_version", "policy_config"),
            "policy_config.policy_version",
        ),
        evidence_schema_version=_non_empty_string(
            _field(data, "evidence_schema_version", "policy_config"),
            "policy_config.evidence_schema_version",
        ),
        supported_stage=_enum(
            RolloutStage,
            _field(data, "supported_stage", "policy_config"),
            "policy_config.supported_stage",
        ),
        required_segments=_string_tuple(
            _field(data, "required_segments", "policy_config"),
            "policy_config.required_segments",
        ),
        minimum_paired_samples=_non_negative_integer(
            _field(data, "minimum_paired_samples", "policy_config"),
            "policy_config.minimum_paired_samples",
        ),
        minimum_pairs_per_segment=_non_negative_integer(
            _field(data, "minimum_pairs_per_segment", "policy_config"),
            "policy_config.minimum_pairs_per_segment",
        ),
        minimum_observation_duration_seconds=_non_negative_number(
            _field(data, "minimum_observation_duration_seconds", "policy_config"),
            "policy_config.minimum_observation_duration_seconds",
        ),
        required_evaluators=tuple(
            _parse_evaluator_requirement(
                item, f"policy_config.required_evaluators[{index}]"
            )
            for index, item in enumerate(
                _sequence(
                    _field(data, "required_evaluators", "policy_config"),
                    "policy_config.required_evaluators",
                )
            )
        ),
        critical_finding_severities=tuple(
            _enum(
                FindingSeverity,
                item,
                f"policy_config.critical_finding_severities[{index}]",
            )
            for index, item in enumerate(
                _sequence(
                    _field(data, "critical_finding_severities", "policy_config"),
                    "policy_config.critical_finding_severities",
                )
            )
        ),
        forbidden_policy_violations=_string_tuple(
            _field(data, "forbidden_policy_violations", "policy_config"),
            "policy_config.forbidden_policy_violations",
        ),
        maximum_candidate_failure_rate=_rate(
            _field(data, "maximum_candidate_failure_rate", "policy_config"),
            "policy_config.maximum_candidate_failure_rate",
        ),
        maximum_failure_rate_regression=_rate(
            _field(data, "maximum_failure_rate_regression", "policy_config"),
            "policy_config.maximum_failure_rate_regression",
        ),
        quality_non_inferiority_margin=_rate(
            _field(data, "quality_non_inferiority_margin", "policy_config"),
            "policy_config.quality_non_inferiority_margin",
        ),
        finding_delta_limits=tuple(
            _parse_finding_delta_limit(
                item, f"policy_config.finding_delta_limits[{index}]"
            )
            for index, item in enumerate(
                _sequence(
                    _field(data, "finding_delta_limits", "policy_config"),
                    "policy_config.finding_delta_limits",
                )
            )
        ),
        efficiency_guardrails=tuple(
            _parse_metric_guardrail(
                item, f"policy_config.efficiency_guardrails[{index}]"
            )
            for index, item in enumerate(
                _sequence(
                    _field(data, "efficiency_guardrails", "policy_config"),
                    "policy_config.efficiency_guardrails",
                )
            )
        ),
        require_objective=_boolean(
            _field(data, "require_objective", "policy_config"),
            "policy_config.require_objective",
        ),
        minimum_objective_improvement=_rate(
            _field(data, "minimum_objective_improvement", "policy_config"),
            "policy_config.minimum_objective_improvement",
        ),
        human_review_on_evaluator_conflict=_boolean(
            _field(data, "human_review_on_evaluator_conflict", "policy_config"),
            "policy_config.human_review_on_evaluator_conflict",
        ),
    )


def _parse_pair(value: object, path: str) -> PairedEvidence:
    data = _mapping(value, path)
    return PairedEvidence(
        pair_id=_non_empty_string(_field(data, "pair_id", path), f"{path}.pair_id"),
        task_id=_non_empty_string(_field(data, "task_id", path), f"{path}.task_id"),
        segment=_non_empty_string(_field(data, "segment", path), f"{path}.segment"),
        output_type=_enum(
            OutputType, _field(data, "output_type", path), f"{path}.output_type"
        ),
        baseline=_parse_attempt(_field(data, "baseline", path), f"{path}.baseline"),
        candidate=_parse_attempt(_field(data, "candidate", path), f"{path}.candidate"),
    )


def _parse_attempt(value: object, path: str) -> AttemptEvidence:
    data = _mapping(value, path)
    return AttemptEvidence(
        attempt_id=_non_empty_string(
            _field(data, "attempt_id", path), f"{path}.attempt_id"
        ),
        source_revision=_non_empty_string(
            _field(data, "source_revision", path), f"{path}.source_revision"
        ),
        prompt_hash=_non_empty_string(
            _field(data, "prompt_hash", path), f"{path}.prompt_hash"
        ),
        model=_non_empty_string(_field(data, "model", path), f"{path}.model"),
        runner=_non_empty_string(_field(data, "runner", path), f"{path}.runner"),
        tool_policy=_non_empty_string(
            _field(data, "tool_policy", path), f"{path}.tool_policy"
        ),
        execution_status=_enum(
            ExecutionStatus,
            _field(data, "execution_status", path),
            f"{path}.execution_status",
        ),
        deterministic_result=_enum(
            DeterministicResult,
            _field(data, "deterministic_result", path),
            f"{path}.deterministic_result",
        ),
        greptile=_parse_greptile(_field(data, "greptile", path), f"{path}.greptile"),
        metrics=_parse_metrics(_field(data, "metrics", path), f"{path}.metrics"),
        policy_violations=_string_tuple(
            _field(data, "policy_violations", path),
            f"{path}.policy_violations",
        ),
    )


def _parse_greptile(value: object, path: str) -> GreptileEvidence:
    data = _mapping(value, path)
    return GreptileEvidence(
        status=_enum(EvaluatorStatus, _field(data, "status", path), f"{path}.status"),
        findings=tuple(
            _parse_finding(item, f"{path}.findings[{index}]")
            for index, item in enumerate(
                _sequence(_field(data, "findings", path), f"{path}.findings")
            )
        ),
    )


def _parse_finding(value: object, path: str) -> GreptileFinding:
    data = _mapping(value, path)
    file_path_value = data.get("file_path")
    return GreptileFinding(
        finding_id=_non_empty_string(
            _field(data, "finding_id", path), f"{path}.finding_id"
        ),
        severity=_enum(
            FindingSeverity, _field(data, "severity", path), f"{path}.severity"
        ),
        category=_non_empty_string(_field(data, "category", path), f"{path}.category"),
        file_path=None
        if file_path_value is None
        else _non_empty_string(file_path_value, f"{path}.file_path"),
    )


def _parse_metrics(value: object, path: str) -> AttemptMetrics:
    data = _mapping(value, path)
    return AttemptMetrics(
        duration_ms=_optional_non_negative_number(
            data.get("duration_ms"), f"{path}.duration_ms"
        ),
        total_tokens=_optional_non_negative_integer(
            data.get("total_tokens"), f"{path}.total_tokens"
        ),
        tool_call_count=_optional_non_negative_integer(
            data.get("tool_call_count"), f"{path}.tool_call_count"
        ),
        estimated_cost_usd=_optional_non_negative_number(
            data.get("estimated_cost_usd"),
            f"{path}.estimated_cost_usd",
        ),
    )


def _parse_objective(value: object, path: str) -> Objective:
    data = _mapping(value, path)
    return Objective(
        metric=_enum(ObjectiveMetric, _field(data, "metric", path), f"{path}.metric"),
    )


def _parse_evaluator_requirement(value: object, path: str) -> EvaluatorRequirement:
    data = _mapping(value, path)
    return EvaluatorRequirement(
        output_type=_enum(
            OutputType, _field(data, "output_type", path), f"{path}.output_type"
        ),
        evaluators=tuple(
            _enum(EvaluatorName, item, f"{path}.evaluators[{index}]")
            for index, item in enumerate(
                _sequence(_field(data, "evaluators", path), f"{path}.evaluators")
            )
        ),
    )


def _parse_finding_delta_limit(value: object, path: str) -> FindingDeltaLimit:
    data = _mapping(value, path)
    return FindingDeltaLimit(
        severity=_enum(
            FindingSeverity, _field(data, "severity", path), f"{path}.severity"
        ),
        maximum_candidate_delta=_non_negative_integer(
            _field(data, "maximum_candidate_delta", path),
            f"{path}.maximum_candidate_delta",
        ),
    )


def _parse_metric_guardrail(value: object, path: str) -> MetricGuardrail:
    data = _mapping(value, path)
    return MetricGuardrail(
        metric=_enum(MetricName, _field(data, "metric", path), f"{path}.metric"),
        maximum_candidate_to_baseline_ratio=_non_negative_number(
            _field(data, "maximum_candidate_to_baseline_ratio", path),
            f"{path}.maximum_candidate_to_baseline_ratio",
        ),
    )


def _field(data: Mapping[str, object], name: str, path: str) -> object:
    if name not in data:
        raise ContractError(f"{path}.{name} is required")
    return data[name]


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ContractError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ContractError(f"{path} contains a non-string key")
        result[key] = item
    return result


def _sequence(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ContractError(f"{path} must be an array")
    return list(value)


def _non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path} must be a non-empty string")
    return value


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    return tuple(
        _non_empty_string(item, f"{path}[{index}]")
        for index, item in enumerate(_sequence(value, path))
    )


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{path} must be a boolean")
    return value


def _non_negative_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{path} must be a non-negative integer")
    return value


def _non_negative_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ContractError(f"{path} must be a non-negative number")
    number = float(value)
    if number < 0 or not math.isfinite(number):
        raise ContractError(f"{path} must be a finite non-negative number")
    return number


def _optional_non_negative_number(value: object, path: str) -> float | None:
    if value is None:
        return None
    return _non_negative_number(value, path)


def _optional_non_negative_integer(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _non_negative_integer(value, path)


def _rate(value: object, path: str) -> float:
    number = _non_negative_number(value, path)
    if number > 1:
        raise ContractError(f"{path} must be between 0 and 1")
    return number


def _enum(enum_type: type[EnumValue], value: object, path: str) -> EnumValue:
    raw_value = _non_empty_string(value, path)
    try:
        return enum_type(raw_value)
    except ValueError as exc:
        supported = ", ".join(item.value for item in enum_type)
        raise ContractError(f"{path} must be one of: {supported}") from exc
