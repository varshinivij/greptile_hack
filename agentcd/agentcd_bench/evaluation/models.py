"""Versioned policy input, configuration, and decision models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


EVIDENCE_SCHEMA_VERSION = "agentcd.evaluation.evidence/v1"
POLICY_CONFIG_SCHEMA_VERSION = "agentcd.evaluation.policy-config/v1"
DECISION_SCHEMA_VERSION = "agentcd.evaluation.decision/v1"
OFFLINE_POLICY_VERSION = "offline-v1"

Scalar: TypeAlias = str | int | float | bool | None


class ContractError(ValueError):
    """Raised when evidence or policy configuration violates its versioned contract."""


class RolloutStage(StrEnum):
    OFFLINE = "offline"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"


class DecisionAction(StrEnum):
    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"
    ROLLBACK = "rollback"
    HUMAN_REVIEW = "human_review"


class OutputType(StrEnum):
    CODE = "code"
    TEXT = "text"
    STRUCTURED = "structured"


class ExecutionStatus(StrEnum):
    SUCCESS = "success"
    TASK_FAILURE = "task_failure"
    TIMEOUT = "timeout"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class DeterministicResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class EvaluatorStatus(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class EvaluatorName(StrEnum):
    DETERMINISTIC = "deterministic"
    GREPTILE = "greptile"


class FindingSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MetricName(StrEnum):
    DURATION_MS = "duration_ms"
    TOTAL_TOKENS = "total_tokens"
    TOOL_CALL_COUNT = "tool_call_count"
    ESTIMATED_COST_USD = "estimated_cost_usd"


class ObjectiveMetric(StrEnum):
    QUALITY_PASS_RATE = "quality_pass_rate"
    DURATION_MS = "duration_ms"
    TOTAL_TOKENS = "total_tokens"
    TOOL_CALL_COUNT = "tool_call_count"
    ESTIMATED_COST_USD = "estimated_cost_usd"


class GateName(StrEnum):
    EVIDENCE_VALIDITY = "evidence_validity"
    SAFETY = "safety"
    EVIDENCE_COMPLETENESS = "evidence_completeness"
    RELIABILITY = "reliability"
    QUALITY = "quality"
    EFFICIENCY_AND_OBJECTIVE = "efficiency_and_objective"


class GateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    HELD = "held"
    REVIEW = "review"
    NOT_EVALUATED = "not_evaluated"


class ReasonCode(StrEnum):
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    EVIDENCE_INCOMPARABLE = "EVIDENCE_INCOMPARABLE"
    SAMPLE_TOO_SMALL = "SAMPLE_TOO_SMALL"
    SEGMENT_COVERAGE_MISSING = "SEGMENT_COVERAGE_MISSING"
    OBSERVATION_WINDOW_TOO_SHORT = "OBSERVATION_WINDOW_TOO_SHORT"
    CRITICAL_FINDING = "CRITICAL_FINDING"
    FORBIDDEN_SIDE_EFFECT = "FORBIDDEN_SIDE_EFFECT"
    RELIABILITY_REGRESSION = "RELIABILITY_REGRESSION"
    QUALITY_REGRESSION = "QUALITY_REGRESSION"
    EFFICIENCY_GUARDRAIL_FAILED = "EFFICIENCY_GUARDRAIL_FAILED"
    OBJECTIVE_NOT_MET = "OBJECTIVE_NOT_MET"
    EVALUATOR_CONFLICT = "EVALUATOR_CONFLICT"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    ALL_GATES_PASSED = "ALL_GATES_PASSED"


@dataclass(frozen=True)
class GreptileFinding:
    finding_id: str
    severity: FindingSeverity
    category: str
    file_path: str | None


@dataclass(frozen=True)
class GreptileEvidence:
    status: EvaluatorStatus
    findings: tuple[GreptileFinding, ...]


@dataclass(frozen=True)
class AttemptMetrics:
    duration_ms: float | None
    total_tokens: int | None
    tool_call_count: int | None
    estimated_cost_usd: float | None

    def value(self, metric: MetricName) -> float | None:
        if metric is MetricName.DURATION_MS:
            return self.duration_ms
        if metric is MetricName.TOTAL_TOKENS:
            return float(self.total_tokens) if self.total_tokens is not None else None
        if metric is MetricName.TOOL_CALL_COUNT:
            return (
                float(self.tool_call_count)
                if self.tool_call_count is not None
                else None
            )
        if metric is MetricName.ESTIMATED_COST_USD:
            return self.estimated_cost_usd
        raise ValueError(f"unsupported metric: {metric}")


@dataclass(frozen=True)
class AttemptEvidence:
    attempt_id: str
    source_revision: str
    prompt_hash: str
    model: str
    runner: str
    tool_policy: str
    execution_status: ExecutionStatus
    deterministic_result: DeterministicResult
    greptile: GreptileEvidence
    metrics: AttemptMetrics
    policy_violations: tuple[str, ...]


@dataclass(frozen=True)
class PairedEvidence:
    pair_id: str
    task_id: str
    segment: str
    output_type: OutputType
    baseline: AttemptEvidence
    candidate: AttemptEvidence


@dataclass(frozen=True)
class Objective:
    metric: ObjectiveMetric


@dataclass(frozen=True)
class EvaluationEvidence:
    schema_version: str
    baseline_version: str
    candidate_version: str
    stage: RolloutStage
    suite_version: str
    observation_duration_seconds: float
    objective: Objective | None
    pairs: tuple[PairedEvidence, ...]


@dataclass(frozen=True)
class EvaluatorRequirement:
    output_type: OutputType
    evaluators: tuple[EvaluatorName, ...]


@dataclass(frozen=True)
class FindingDeltaLimit:
    severity: FindingSeverity
    maximum_candidate_delta: int


@dataclass(frozen=True)
class MetricGuardrail:
    metric: MetricName
    maximum_candidate_to_baseline_ratio: float


@dataclass(frozen=True)
class PolicyConfig:
    schema_version: str
    policy_id: str
    policy_version: str
    evidence_schema_version: str
    supported_stage: RolloutStage
    required_segments: tuple[str, ...]
    minimum_paired_samples: int
    minimum_pairs_per_segment: int
    minimum_observation_duration_seconds: float
    required_evaluators: tuple[EvaluatorRequirement, ...]
    critical_finding_severities: tuple[FindingSeverity, ...]
    forbidden_policy_violations: tuple[str, ...]
    maximum_candidate_failure_rate: float
    maximum_failure_rate_regression: float
    quality_non_inferiority_margin: float
    finding_delta_limits: tuple[FindingDeltaLimit, ...]
    efficiency_guardrails: tuple[MetricGuardrail, ...]
    require_objective: bool
    minimum_objective_improvement: float
    human_review_on_evaluator_conflict: bool


@dataclass(frozen=True)
class Observation:
    metric: str
    baseline: Scalar = None
    candidate: Scalar = None
    observed: Scalar = None
    threshold: Scalar = None

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "observed": self.observed,
            "threshold": self.threshold,
        }


@dataclass(frozen=True)
class GateResult:
    name: GateName
    status: GateStatus
    reason_codes: tuple[ReasonCode, ...]
    summary: str
    observations: tuple[Observation, ...] = ()
    missing_evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "reason_codes": [reason.value for reason in self.reason_codes],
            "summary": self.summary,
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
            "missing_evidence": list(self.missing_evidence),
        }


@dataclass(frozen=True)
class DecisionReport:
    action: DecisionAction
    current_stage: RolloutStage
    next_stage: RolloutStage | None
    evidence_schema_version: str
    policy_id: str
    policy_version: str
    baseline_version: str
    candidate_version: str
    reason_codes: tuple[ReasonCode, ...]
    summary: str
    gate_results: tuple[GateResult, ...]
    paired_sample_count: int
    segment_counts: tuple[tuple[str, int], ...]
    missing_evidence: tuple[str, ...]
    schema_version: str = DECISION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "action": self.action.value,
            "current_stage": self.current_stage.value,
            "next_stage": self.next_stage.value if self.next_stage else None,
            "evidence_schema_version": self.evidence_schema_version,
            "policy": {
                "id": self.policy_id,
                "version": self.policy_version,
            },
            "versions": {
                "baseline": self.baseline_version,
                "candidate": self.candidate_version,
            },
            "reason_codes": [reason.value for reason in self.reason_codes],
            "summary": self.summary,
            "gates": [gate.to_dict() for gate in self.gate_results],
            "coverage": {
                "paired_samples": self.paired_sample_count,
                "segments": dict(self.segment_counts),
            },
            "missing_evidence": list(self.missing_evidence),
        }
