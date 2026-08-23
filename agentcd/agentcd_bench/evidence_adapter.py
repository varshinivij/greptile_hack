"""Normalize benchmark attempts and raw Greptile responses into policy evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .evaluation.models import (
    EVIDENCE_SCHEMA_VERSION,
    AttemptEvidence,
    AttemptMetrics,
    DeterministicResult,
    EvaluationEvidence,
    EvaluatorStatus,
    ExecutionStatus,
    FindingSeverity,
    GreptileEvidence,
    GreptileFinding,
    Objective,
    ObjectiveMetric,
    OutputType,
    PairedEvidence,
    RolloutStage,
)


GREPTILE_SEVERITIES = {
    "P0": FindingSeverity.CRITICAL,
    "P1": FindingSeverity.HIGH,
    "P2": FindingSeverity.MEDIUM,
    "critical": FindingSeverity.CRITICAL,
    "high": FindingSeverity.HIGH,
    "medium": FindingSeverity.MEDIUM,
    "low": FindingSeverity.LOW,
    "info": FindingSeverity.INFO,
}


class EvidenceAdapterError(ValueError):
    """Raised when benchmark and evaluator artifacts cannot be paired safely."""


def build_evaluation_evidence(
    *,
    raw_evaluations: Sequence[Mapping[str, object]],
    candidate_attempts: Sequence[Mapping[str, object]],
    baseline_attempts: Sequence[Mapping[str, object]],
    candidate_version: str,
    baseline_version: str,
    candidate_source_revision: str,
    baseline_source_revision: str,
    prompt_hash: str,
    task_id: str,
    suite_version: str,
    segment: str,
    output_type: OutputType,
    runner: str,
    tool_policy: str,
    objective_metric: ObjectiveMetric | None = None,
) -> EvaluationEvidence:
    """Build named, paired policy evidence without performing I/O."""
    if not (
        len(raw_evaluations) == len(candidate_attempts) == len(baseline_attempts)
    ):
        raise EvidenceAdapterError(
            "raw evaluations, candidate attempts, and baseline attempts must have equal lengths"
        )

    evaluations_by_run = _index_by_run(raw_evaluations, "raw_evaluations")
    candidate_by_run = _index_by_run(candidate_attempts, "candidate_attempts")
    baseline_by_run = _index_by_run(baseline_attempts, "baseline_attempts")
    if evaluations_by_run.keys() != candidate_by_run.keys() or (
        evaluations_by_run.keys() != baseline_by_run.keys()
    ):
        raise EvidenceAdapterError(
            "raw evaluations and attempts must contain the same run indexes"
        )

    pairs = tuple(
        _build_pair(
            run_index=run_index,
            raw_evaluation=evaluations_by_run[run_index],
            candidate_attempt=candidate_by_run[run_index],
            baseline_attempt=baseline_by_run[run_index],
            candidate_source_revision=candidate_source_revision,
            baseline_source_revision=baseline_source_revision,
            prompt_hash=prompt_hash,
            task_id=task_id,
            segment=segment,
            output_type=output_type,
            runner=runner,
            tool_policy=tool_policy,
        )
        for run_index in sorted(evaluations_by_run)
    )
    return EvaluationEvidence(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        stage=RolloutStage.OFFLINE,
        suite_version=suite_version,
        observation_duration_seconds=_observation_duration_seconds(pairs),
        objective=(Objective(objective_metric) if objective_metric else None),
        pairs=pairs,
    )


def _index_by_run(
    values: Sequence[Mapping[str, object]], path: str
) -> dict[int, Mapping[str, object]]:
    indexed: dict[int, Mapping[str, object]] = {}
    for index, value in enumerate(values):
        run_index = value.get("run_index")
        if not isinstance(run_index, int) or isinstance(run_index, bool):
            raise EvidenceAdapterError(f"{path}[{index}].run_index must be an integer")
        if run_index in indexed:
            raise EvidenceAdapterError(f"{path} contains duplicate run index {run_index}")
        indexed[run_index] = value
    return indexed


def _build_pair(
    *,
    run_index: int,
    raw_evaluation: Mapping[str, object],
    candidate_attempt: Mapping[str, object],
    baseline_attempt: Mapping[str, object],
    candidate_source_revision: str,
    baseline_source_revision: str,
    prompt_hash: str,
    task_id: str,
    segment: str,
    output_type: OutputType,
    runner: str,
    tool_policy: str,
) -> PairedEvidence:
    result = _mapping(raw_evaluation.get("result"), f"evaluations[{run_index}].result")
    evaluations = _mapping(
        result.get("evaluations"), f"evaluations[{run_index}].result.evaluations"
    )
    candidate_greptile = _normalize_greptile(
        evaluations.get("a"), candidate_attempt, f"evaluations[{run_index}].a"
    )
    baseline_greptile = _normalize_greptile(
        evaluations.get("b"), baseline_attempt, f"evaluations[{run_index}].b"
    )
    return PairedEvidence(
        pair_id=f"{task_id}-run-{run_index}",
        task_id=task_id,
        segment=segment,
        output_type=output_type,
        baseline=_normalize_attempt(
            baseline_attempt,
            role="baseline",
            run_index=run_index,
            source_revision=baseline_source_revision,
            prompt_hash=prompt_hash,
            runner=runner,
            tool_policy=tool_policy,
            greptile=baseline_greptile,
        ),
        candidate=_normalize_attempt(
            candidate_attempt,
            role="candidate",
            run_index=run_index,
            source_revision=candidate_source_revision,
            prompt_hash=prompt_hash,
            runner=runner,
            tool_policy=tool_policy,
            greptile=candidate_greptile,
        ),
    )


def _normalize_attempt(
    attempt: Mapping[str, object],
    *,
    role: str,
    run_index: int,
    source_revision: str,
    prompt_hash: str,
    runner: str,
    tool_policy: str,
    greptile: GreptileEvidence,
) -> AttemptEvidence:
    llm_metrics = _optional_mapping(attempt.get("llm_metrics"))
    tool_metrics = _optional_mapping(attempt.get("tool_metrics"))
    artifact = _optional_mapping(attempt.get("artifact"))
    artifact_id = artifact.get("commit_id")
    suffix = str(artifact_id) if artifact_id else str(run_index)
    return AttemptEvidence(
        attempt_id=f"{role}-{suffix}",
        source_revision=source_revision,
        prompt_hash=prompt_hash,
        model=_model(llm_metrics.get("model"), role),
        runner=runner,
        tool_policy=tool_policy,
        execution_status=_execution_status(attempt.get("status")),
        deterministic_result=_deterministic_result(
            attempt.get("deterministic_result")
        ),
        greptile=greptile,
        metrics=AttemptMetrics(
            duration_ms=_number(llm_metrics.get("duration_ms")),
            total_tokens=_integer(llm_metrics.get("total_tokens")),
            tool_call_count=_integer(tool_metrics.get("tool_call_count")),
            estimated_cost_usd=_number(llm_metrics.get("estimated_cost_usd")),
        ),
        policy_violations=_string_tuple(attempt.get("policy_violations")),
    )


def _normalize_greptile(
    raw_result: object,
    attempt: Mapping[str, object],
    path: str,
) -> GreptileEvidence:
    result = _mapping(raw_result, path)
    _validate_evaluation_commit(result, attempt, path)
    if result.get("status") != "success":
        return GreptileEvidence(status=EvaluatorStatus.UNAVAILABLE, findings=())

    output = result.get("greptile_output")
    if not isinstance(output, Mapping):
        return GreptileEvidence(status=EvaluatorStatus.UNAVAILABLE, findings=())
    comments = output.get("comments")
    if not isinstance(comments, list):
        return GreptileEvidence(status=EvaluatorStatus.UNAVAILABLE, findings=())

    findings: list[GreptileFinding] = []
    for index, value in enumerate(comments):
        finding = _normalize_finding(value, f"{path}.greptile_output.comments[{index}]")
        if finding is None:
            return GreptileEvidence(status=EvaluatorStatus.UNAVAILABLE, findings=())
        findings.append(finding)
    return GreptileEvidence(
        status=EvaluatorStatus.COMPLETED,
        findings=tuple(findings),
    )


def _normalize_finding(value: object, path: str) -> GreptileFinding | None:
    if not isinstance(value, Mapping):
        return None
    finding_id = value.get("id")
    file_path = value.get("path")
    category = value.get("category")
    severity = value.get("severity")
    if not isinstance(finding_id, (str, int)) or isinstance(finding_id, bool):
        return None
    if not isinstance(file_path, str) or not file_path:
        return None
    if not isinstance(category, str) or not category:
        return None
    if not isinstance(severity, str) or severity not in GREPTILE_SEVERITIES:
        return None
    return GreptileFinding(
        finding_id=str(finding_id),
        severity=GREPTILE_SEVERITIES[severity],
        category=category,
        file_path=file_path,
    )


def _validate_evaluation_commit(
    result: Mapping[str, object], attempt: Mapping[str, object], path: str
) -> None:
    artifact = _mapping(attempt.get("artifact"), f"{path}.attempt.artifact")
    expected = artifact.get("commit_id")
    actual = result.get("commit_id")
    if not isinstance(expected, str) or actual != expected:
        raise EvidenceAdapterError(
            f"{path}.commit_id does not match the paired attempt artifact"
        )


def _execution_status(value: object) -> ExecutionStatus:
    if value == "success":
        return ExecutionStatus.SUCCESS
    if value in ("error", "failure"):
        return ExecutionStatus.TASK_FAILURE
    return ExecutionStatus.INFRASTRUCTURE_ERROR


def _deterministic_result(value: object) -> DeterministicResult:
    if isinstance(value, str):
        try:
            return DeterministicResult(value)
        except ValueError:
            pass
    return DeterministicResult.UNAVAILABLE


def _observation_duration_seconds(pairs: tuple[PairedEvidence, ...]) -> float:
    baseline_ms = sum(pair.baseline.metrics.duration_ms or 0 for pair in pairs)
    candidate_ms = sum(pair.candidate.metrics.duration_ms or 0 for pair in pairs)
    return max(baseline_ms, candidate_ms) / 1000


def _model(value: object, role: str) -> str:
    if isinstance(value, str) and value:
        return value
    return f"unknown-{role}"


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvidenceAdapterError(f"{path} must be an object")
    return value


def _optional_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)
