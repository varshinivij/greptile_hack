"""Shared calculations for independent policy gates."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import mean

from .models import (
    AttemptEvidence,
    DeterministicResult,
    EvaluationEvidence,
    EvaluatorName,
    EvaluatorStatus,
    ExecutionStatus,
    FindingSeverity,
    MetricName,
    OutputType,
    PairedEvidence,
    PolicyConfig,
)


def comparison_scopes(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
    *,
    include_pairs: bool,
) -> tuple[tuple[str | None, tuple[PairedEvidence, ...]], ...]:
    scopes: list[tuple[str | None, tuple[PairedEvidence, ...]]] = [
        (None, evidence.pairs)
    ]
    segment_sizes: dict[str, int] = {}
    for segment in config.required_segments:
        pairs = tuple(pair for pair in evidence.pairs if pair.segment == segment)
        if pairs:
            scopes.append((f"segment.{segment}", pairs))
            segment_sizes[segment] = len(pairs)
    if include_pairs:
        scopes.extend(
            (f"pair.{pair.pair_id}", (pair,))
            for pair in evidence.pairs
            if segment_sizes.get(pair.segment) != 1
        )
    return tuple(scopes)


def scoped_metric(scope: str | None, metric: str) -> str:
    if scope is None:
        return metric
    return f"{scope}.{metric}"


def required_evaluators(
    config: PolicyConfig,
    output_type: OutputType,
) -> tuple[EvaluatorName, ...]:
    for requirement in config.required_evaluators:
        if requirement.output_type is output_type:
            return requirement.evaluators
    message = f"missing validated evaluator requirement for {output_type.value}"
    raise RuntimeError(message)


def pair_has_completed_evaluator(
    pair: PairedEvidence,
    evaluator: EvaluatorName,
) -> bool:
    if not both_succeeded(pair):
        return False
    for attempt in (pair.baseline, pair.candidate):
        if (
            evaluator is EvaluatorName.DETERMINISTIC
            and attempt.deterministic_result
            not in (DeterministicResult.PASSED, DeterministicResult.FAILED)
        ):
            return False
        if (
            evaluator is EvaluatorName.GREPTILE
            and attempt.greptile.status is not EvaluatorStatus.COMPLETED
        ):
            return False
    return True


def both_succeeded(pair: PairedEvidence) -> bool:
    return (
        pair.baseline.execution_status is ExecutionStatus.SUCCESS
        and pair.candidate.execution_status is ExecutionStatus.SUCCESS
    )


def failure_rate(attempts: Iterable[AttemptEvidence]) -> float:
    attempt_list = list(attempts)
    if not attempt_list:
        return 0.0
    failures = sum(
        attempt.execution_status
        in (ExecutionStatus.TASK_FAILURE, ExecutionStatus.TIMEOUT)
        for attempt in attempt_list
    )
    return failures / len(attempt_list)


def deterministic_pass_rates(
    scoped_pairs: Iterable[PairedEvidence],
    config: PolicyConfig,
) -> tuple[float, float] | None:
    pairs = [
        pair
        for pair in scoped_pairs
        if both_succeeded(pair)
        and EvaluatorName.DETERMINISTIC in required_evaluators(config, pair.output_type)
        and pair.baseline.deterministic_result
        in (DeterministicResult.PASSED, DeterministicResult.FAILED)
        and pair.candidate.deterministic_result
        in (DeterministicResult.PASSED, DeterministicResult.FAILED)
    ]
    if not pairs:
        return None
    baseline_passes = sum(
        pair.baseline.deterministic_result is DeterministicResult.PASSED
        for pair in pairs
    )
    candidate_passes = sum(
        pair.candidate.deterministic_result is DeterministicResult.PASSED
        for pair in pairs
    )
    return baseline_passes / len(pairs), candidate_passes / len(pairs)


def finding_count(
    scoped_pairs: Iterable[PairedEvidence],
    severity: FindingSeverity,
    *,
    candidate: bool,
) -> int:
    count = 0
    for pair in scoped_pairs:
        attempt = pair.candidate if candidate else pair.baseline
        if attempt.greptile.status is not EvaluatorStatus.COMPLETED:
            continue
        count += sum(
            finding.severity is severity for finding in attempt.greptile.findings
        )
    return count


def metric_averages(
    scoped_pairs: Iterable[PairedEvidence],
    metric: MetricName,
) -> tuple[float, float] | None:
    pairs = [pair for pair in scoped_pairs if both_succeeded(pair)]
    baseline_values = [pair.baseline.metrics.value(metric) for pair in pairs]
    candidate_values = [pair.candidate.metrics.value(metric) for pair in pairs]
    if not baseline_values or any(
        value is None for value in baseline_values + candidate_values
    ):
        return None
    return (
        mean(value for value in baseline_values if value is not None),
        mean(value for value in candidate_values if value is not None),
    )


def ratio(candidate: float, baseline: float) -> float | None:
    if baseline == 0:
        return 1.0 if candidate == 0 else None
    return candidate / baseline


def rounded(value: float) -> float:
    result = round(value, 6)
    return 0.0 if result == 0 else result
