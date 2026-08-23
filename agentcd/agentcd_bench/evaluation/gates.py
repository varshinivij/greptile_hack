"""Independent gates for the offline evaluation policy."""

from __future__ import annotations

from collections import Counter

from .calculations import (
    both_succeeded as _both_succeeded,
    comparison_scopes as _comparison_scopes,
    deterministic_pass_rates as _deterministic_pass_rates,
    failure_rate as _failure_rate,
    finding_count as _finding_count,
    metric_averages as _metric_averages,
    ratio as _ratio,
    rounded as _rounded,
    scoped_metric as _scoped_metric,
)
from .models import (
    EvaluationEvidence,
    FindingSeverity,
    GateName,
    GateResult,
    GateStatus,
    MetricName,
    ObjectiveMetric,
    Observation,
    PolicyConfig,
    ReasonCode,
)


def evaluate_evidence_validity(
    evidence: EvaluationEvidence, config: PolicyConfig
) -> GateResult:
    mismatches: list[Observation] = []
    comparable_fields = (
        "source_revision",
        "prompt_hash",
        "model",
        "runner",
        "tool_policy",
    )
    for pair in evidence.pairs:
        for field in comparable_fields:
            baseline_value = getattr(pair.baseline, field)
            candidate_value = getattr(pair.candidate, field)
            if baseline_value == candidate_value:
                continue
            mismatches.append(
                Observation(
                    metric=f"{pair.pair_id}.{field}",
                    baseline=baseline_value,
                    candidate=candidate_value,
                    threshold="equal",
                )
            )

    observations = [
        Observation(
            metric="incomparable_configuration_values",
            observed=len(mismatches),
            threshold=0,
        ),
        *mismatches,
    ]
    if mismatches:
        return GateResult(
            name=GateName.EVIDENCE_VALIDITY,
            status=GateStatus.HELD,
            reason_codes=(ReasonCode.EVIDENCE_INCOMPARABLE,),
            summary=f"{len(mismatches)} baseline/candidate configuration values are not comparable.",
            observations=tuple(observations),
        )
    return GateResult(
        name=GateName.EVIDENCE_VALIDITY,
        status=GateStatus.PASSED,
        reason_codes=(),
        summary="All paired attempts use comparable source, prompt, model, runner, and tool configuration.",
        observations=tuple(observations),
    )


def evaluate_safety(evidence: EvaluationEvidence, config: PolicyConfig) -> GateResult:
    critical_severities = set(config.critical_finding_severities)
    forbidden_violations = set(config.forbidden_policy_violations)
    critical_counts: Counter[FindingSeverity] = Counter()
    baseline_critical_counts: Counter[FindingSeverity] = Counter()
    violations: Counter[str] = Counter()

    for pair in evidence.pairs:
        for finding in pair.baseline.greptile.findings:
            if finding.severity in critical_severities:
                baseline_critical_counts[finding.severity] += 1
        for finding in pair.candidate.greptile.findings:
            if finding.severity in critical_severities:
                critical_counts[finding.severity] += 1
        for violation in pair.candidate.policy_violations:
            if violation in forbidden_violations:
                violations[violation] += 1

    observations: list[Observation] = [
        Observation(
            metric="candidate_critical_finding_count",
            observed=sum(critical_counts.values()),
            threshold=0,
        ),
        Observation(
            metric="candidate_forbidden_policy_violation_count",
            observed=sum(violations.values()),
            threshold=0,
        ),
    ]
    for severity in sorted(critical_counts, key=lambda item: item.value):
        observations.append(
            Observation(
                metric=f"greptile_findings.{severity.value}",
                baseline=baseline_critical_counts[severity],
                candidate=critical_counts[severity],
                observed=critical_counts[severity],
                threshold=0,
            )
        )
    for violation in sorted(violations):
        observations.append(
            Observation(
                metric=f"policy_violations.{violation}",
                candidate=violations[violation],
                observed=violations[violation],
                threshold=0,
            )
        )

    reason_codes: list[ReasonCode] = []
    if critical_counts:
        reason_codes.append(ReasonCode.CRITICAL_FINDING)
    if violations:
        reason_codes.append(ReasonCode.FORBIDDEN_SIDE_EFFECT)
    if reason_codes:
        return GateResult(
            name=GateName.SAFETY,
            status=GateStatus.FAILED,
            reason_codes=tuple(reason_codes),
            summary="The candidate contains a configured critical finding or forbidden policy violation.",
            observations=tuple(observations),
        )
    return GateResult(
        name=GateName.SAFETY,
        status=GateStatus.PASSED,
        reason_codes=(),
        summary="No configured critical finding or forbidden policy violation was observed.",
        observations=tuple(observations),
    )


def evaluate_reliability(
    evidence: EvaluationEvidence, config: PolicyConfig
) -> GateResult:
    observations: list[Observation] = []
    failed = False
    for scope, pairs in _comparison_scopes(evidence, config, include_pairs=False):
        baseline_rate = _failure_rate(pair.baseline for pair in pairs)
        candidate_rate = _failure_rate(pair.candidate for pair in pairs)
        regression = candidate_rate - baseline_rate
        observations.extend(
            (
                Observation(
                    metric=_scoped_metric(scope, "execution_failure_rate"),
                    baseline=_rounded(baseline_rate),
                    candidate=_rounded(candidate_rate),
                    observed=_rounded(candidate_rate),
                    threshold=_rounded(config.maximum_candidate_failure_rate),
                ),
                Observation(
                    metric=_scoped_metric(scope, "execution_failure_rate_regression"),
                    baseline=_rounded(baseline_rate),
                    candidate=_rounded(candidate_rate),
                    observed=_rounded(regression),
                    threshold=_rounded(config.maximum_failure_rate_regression),
                ),
            )
        )
        if (
            candidate_rate > config.maximum_candidate_failure_rate
            or regression > config.maximum_failure_rate_regression
        ):
            failed = True
    if failed:
        return GateResult(
            name=GateName.RELIABILITY,
            status=GateStatus.FAILED,
            reason_codes=(ReasonCode.RELIABILITY_REGRESSION,),
            summary="Candidate execution failures or timeouts exceed a configured reliability limit.",
            observations=tuple(observations),
        )
    return GateResult(
        name=GateName.RELIABILITY,
        status=GateStatus.PASSED,
        reason_codes=(),
        summary="Candidate execution reliability is within absolute and baseline-relative limits.",
        observations=tuple(observations),
    )


def evaluate_quality(evidence: EvaluationEvidence, config: PolicyConfig) -> GateResult:
    observations: list[Observation] = []
    failed = False
    conflict = False
    for scope, pairs in _comparison_scopes(evidence, config, include_pairs=False):
        deterministic_rates = _deterministic_pass_rates(pairs, config)
        deterministic_delta = 0.0
        if deterministic_rates:
            baseline_rate, candidate_rate = deterministic_rates
            deterministic_delta = candidate_rate - baseline_rate
            observations.append(
                Observation(
                    metric=_scoped_metric(scope, "deterministic_pass_rate_delta"),
                    baseline=_rounded(baseline_rate),
                    candidate=_rounded(candidate_rate),
                    observed=_rounded(deterministic_delta),
                    threshold=_rounded(-config.quality_non_inferiority_margin),
                )
            )
            if deterministic_delta < -config.quality_non_inferiority_margin:
                failed = True

        aggregate_finding_delta = 0
        for limit in config.finding_delta_limits:
            baseline_count = _finding_count(pairs, limit.severity, candidate=False)
            candidate_count = _finding_count(pairs, limit.severity, candidate=True)
            delta = candidate_count - baseline_count
            aggregate_finding_delta += delta
            observations.append(
                Observation(
                    metric=_scoped_metric(
                        scope, f"greptile_findings.{limit.severity.value}.delta"
                    ),
                    baseline=baseline_count,
                    candidate=candidate_count,
                    observed=delta,
                    threshold=limit.maximum_candidate_delta,
                )
            )
            if delta > limit.maximum_candidate_delta:
                failed = True

        if (
            config.human_review_on_evaluator_conflict
            and deterministic_delta != 0
            and aggregate_finding_delta != 0
            and deterministic_delta * aggregate_finding_delta > 0
        ):
            conflict = True

    if failed:
        return GateResult(
            name=GateName.QUALITY,
            status=GateStatus.FAILED,
            reason_codes=(ReasonCode.QUALITY_REGRESSION,),
            summary="Candidate deterministic outcomes or Greptile finding deltas exceed a quality limit.",
            observations=tuple(observations),
        )

    if conflict:
        return GateResult(
            name=GateName.QUALITY,
            status=GateStatus.REVIEW,
            reason_codes=(
                ReasonCode.EVALUATOR_CONFLICT,
                ReasonCode.MANUAL_REVIEW_REQUIRED,
            ),
            summary="Deterministic outcomes and Greptile findings move in conflicting quality directions.",
            observations=tuple(observations),
        )
    return GateResult(
        name=GateName.QUALITY,
        status=GateStatus.PASSED,
        reason_codes=(),
        summary="Candidate quality is non-inferior within configured deterministic and Greptile limits.",
        observations=tuple(observations),
    )


def evaluate_efficiency_and_objective(
    evidence: EvaluationEvidence, config: PolicyConfig
) -> GateResult:
    observations: list[Observation] = []
    reasons: list[ReasonCode] = []
    missing: set[str] = set()

    for guardrail in config.efficiency_guardrails:
        for scope, pairs in _comparison_scopes(evidence, config, include_pairs=True):
            if not any(_both_succeeded(pair) for pair in pairs):
                continue
            averages = _metric_averages(pairs, guardrail.metric)
            if averages is None:
                missing.add(_scoped_metric(scope, f"metrics.{guardrail.metric.value}"))
                continue
            baseline_value, candidate_value = averages
            ratio = _ratio(candidate_value, baseline_value)
            observed_ratio: float | str = (
                "infinite" if ratio is None else _rounded(ratio)
            )
            observations.append(
                Observation(
                    metric=_scoped_metric(
                        scope,
                        f"{guardrail.metric.value}.candidate_to_baseline_ratio",
                    ),
                    baseline=_rounded(baseline_value),
                    candidate=_rounded(candidate_value),
                    observed=observed_ratio,
                    threshold=_rounded(guardrail.maximum_candidate_to_baseline_ratio),
                )
            )
            if ratio is None or ratio > guardrail.maximum_candidate_to_baseline_ratio:
                _append_once(reasons, ReasonCode.EFFICIENCY_GUARDRAIL_FAILED)

    if evidence.objective:
        objective_observation, objective_met = _evaluate_objective(evidence, config)
        if objective_observation is None:
            missing.add(f"objective.{evidence.objective.metric.value}")
        else:
            observations.append(objective_observation)
            if not objective_met:
                _append_once(reasons, ReasonCode.OBJECTIVE_NOT_MET)

    if missing:
        return GateResult(
            name=GateName.EFFICIENCY_AND_OBJECTIVE,
            status=GateStatus.HELD,
            reason_codes=(ReasonCode.EVIDENCE_INCOMPLETE,),
            summary="Efficiency or objective evidence is incomplete.",
            observations=tuple(observations),
            missing_evidence=tuple(sorted(missing)),
        )
    if reasons:
        return GateResult(
            name=GateName.EFFICIENCY_AND_OBJECTIVE,
            status=GateStatus.FAILED,
            reason_codes=tuple(reasons),
            summary="Candidate efficiency guardrails or its declared objective were not met.",
            observations=tuple(observations),
        )
    return GateResult(
        name=GateName.EFFICIENCY_AND_OBJECTIVE,
        status=GateStatus.PASSED,
        reason_codes=(),
        summary="Candidate efficiency is within guardrails and its declared objective is met.",
        observations=tuple(observations),
    )


def _evaluate_objective(
    evidence: EvaluationEvidence,
    config: PolicyConfig,
) -> tuple[Observation | None, bool]:
    objective = evidence.objective
    if objective is None:
        return None, False
    if objective.metric is ObjectiveMetric.QUALITY_PASS_RATE:
        rates = _deterministic_pass_rates(evidence.pairs, config)
        if rates is None:
            return None, False
        baseline_value, candidate_value = rates
        improvement = candidate_value - baseline_value
    else:
        averages = _metric_averages(evidence.pairs, MetricName(objective.metric.value))
        if averages is None:
            return None, False
        baseline_value, candidate_value = averages
        if baseline_value == 0:
            if candidate_value == 0:
                improvement = 0.0
            else:
                return (
                    Observation(
                        metric=f"objective.{objective.metric.value}.improvement",
                        baseline=0,
                        candidate=_rounded(candidate_value),
                        observed="negative_infinite",
                        threshold=_rounded(config.minimum_objective_improvement),
                    ),
                    False,
                )
        else:
            improvement = (baseline_value - candidate_value) / baseline_value

    return (
        Observation(
            metric=f"objective.{objective.metric.value}.improvement",
            baseline=_rounded(baseline_value),
            candidate=_rounded(candidate_value),
            observed=_rounded(improvement),
            threshold=_rounded(config.minimum_objective_improvement),
        ),
        improvement >= config.minimum_objective_improvement,
    )


def _append_once(reasons: list[ReasonCode], reason: ReasonCode) -> None:
    if reason not in reasons:
        reasons.append(reason)
