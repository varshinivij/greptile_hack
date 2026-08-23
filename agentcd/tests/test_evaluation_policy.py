from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from agentcd_bench.evaluation import (
    ContractError,
    evaluate_policy,
    evaluate_policy_payload,
    parse_evidence,
    parse_policy_config,
)
from agentcd_bench.evaluation.models import (
    DecisionAction,
    DeterministicResult,
    EvaluatorStatus,
    ExecutionStatus,
    FindingSeverity,
    GateName,
    GateStatus,
    GreptileEvidence,
    GreptileFinding,
    MetricName,
    ReasonCode,
    RolloutStage,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evaluation"


class EvaluationPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = parse_evidence(load_json("healthy_evidence.json"))
        self.config = parse_policy_config(load_json("offline_policy.json"))

    def test_healthy_evidence_promotes_deterministically(self) -> None:
        first = evaluate_policy(self.evidence, self.config)
        second = evaluate_policy(self.evidence, self.config)

        self.assertEqual(first.action, DecisionAction.PROMOTE)
        self.assertEqual(first.next_stage, RolloutStage.SHADOW)
        self.assertEqual(first.reason_codes, (ReasonCode.ALL_GATES_PASSED,))
        self.assertEqual(
            [gate.status for gate in first.gate_results], [GateStatus.PASSED] * 6
        )
        self.assertEqual(serialized(first.to_dict()), serialized(second.to_dict()))

    def test_payload_entrypoint_parses_and_evaluates_contracts(self) -> None:
        report = evaluate_policy_payload(
            load_json("healthy_evidence.json"),
            load_json("offline_policy.json"),
        )

        self.assertEqual(report.action, DecisionAction.PROMOTE)
        self.assertEqual(
            report.to_dict()["schema_version"], "agentcd.evaluation.decision/v1"
        )

    def test_saved_scenarios_cover_every_offline_decision_action(self) -> None:
        fixture = require_object(
            load_json("decision_scenarios.json"), "decision_scenarios"
        )
        base_name = require_string(
            fixture["base_evidence"], "decision_scenarios.base_evidence"
        )
        config_name = require_string(
            fixture["policy_config"], "decision_scenarios.policy_config"
        )
        cases = require_array(fixture["cases"], "decision_scenarios.cases")
        observed_actions: set[str] = set()

        for index, case_value in enumerate(cases):
            case = require_object(case_value, f"decision_scenarios.cases[{index}]")
            name = require_string(
                case["name"], f"decision_scenarios.cases[{index}].name"
            )
            expected_action = require_string(
                case["expected_action"],
                f"decision_scenarios.cases[{index}].expected_action",
            )
            evidence_payload = deepcopy(load_json(base_name))
            replacements = require_array(
                case["replacements"],
                f"decision_scenarios.cases[{index}].replacements",
            )
            for replacement_index, replacement_value in enumerate(replacements):
                path_prefix = f"decision_scenarios.cases[{index}].replacements[{replacement_index}]"
                replacement = require_object(replacement_value, path_prefix)
                path = require_array(replacement["path"], f"{path_prefix}.path")
                replace_json_value(evidence_payload, path, replacement["value"])

            with self.subTest(name=name):
                report = evaluate_policy_payload(
                    evidence_payload, load_json(config_name)
                )
                self.assertEqual(report.action.value, expected_action)
                observed_actions.add(report.action.value)

        self.assertEqual(
            observed_actions, {"promote", "hold", "reject", "human_review"}
        )

    def test_missing_required_greptile_evidence_holds(self) -> None:
        pair = self.evidence.pairs[0]
        candidate = replace(
            pair.candidate,
            greptile=GreptileEvidence(status=EvaluatorStatus.UNAVAILABLE, findings=()),
        )
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.HOLD)
        self.assertIn(ReasonCode.EVIDENCE_INCOMPLETE, report.reason_codes)
        self.assertIn(
            "pairs.pair-bug-fix-1.candidate.greptile", report.missing_evidence
        )

    def test_missing_metric_holds_instead_of_treating_it_as_zero(self) -> None:
        pair = self.evidence.pairs[0]
        metrics = replace(pair.candidate.metrics, total_tokens=None)
        candidate = replace(pair.candidate, metrics=metrics)
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.HOLD)
        self.assertIn(ReasonCode.EVIDENCE_INCOMPLETE, report.reason_codes)
        self.assertIn(
            "pairs.pair-bug-fix-1.candidate.metrics.total_tokens",
            report.missing_evidence,
        )

    def test_infrastructure_error_holds_instead_of_counting_as_candidate_failure(
        self,
    ) -> None:
        pair = self.evidence.pairs[0]
        candidate = replace(
            pair.candidate, execution_status=ExecutionStatus.INFRASTRUCTURE_ERROR
        )
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.HOLD)
        self.assertIn(ReasonCode.EVIDENCE_INCOMPLETE, report.reason_codes)
        self.assertNotIn(ReasonCode.RELIABILITY_REGRESSION, report.reason_codes)

    def test_insufficient_samples_and_segment_coverage_hold(self) -> None:
        evidence = replace(self.evidence, pairs=(self.evidence.pairs[0],))

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.HOLD)
        self.assertIn(ReasonCode.SAMPLE_TOO_SMALL, report.reason_codes)
        self.assertIn(ReasonCode.SEGMENT_COVERAGE_MISSING, report.reason_codes)
        self.assertIn("segments.testing", report.missing_evidence)

    def test_incomparable_pair_holds_after_safety_check(self) -> None:
        pair = self.evidence.pairs[0]
        candidate = replace(pair.candidate, model="different-model")
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.HOLD)
        self.assertIn(ReasonCode.EVIDENCE_INCOMPARABLE, report.reason_codes)
        self.assertEqual(report.gate_results[1].name, GateName.SAFETY)
        self.assertEqual(report.gate_results[1].status, GateStatus.PASSED)
        self.assertEqual(report.gate_results[2].status, GateStatus.NOT_EVALUATED)

    def test_critical_finding_rejects_even_when_other_evidence_is_missing(self) -> None:
        first_pair, second_pair = self.evidence.pairs
        critical = GreptileFinding(
            finding_id="candidate-critical-1",
            severity=FindingSeverity.CRITICAL,
            category="security",
            file_path="demo/auth.py",
        )
        first_candidate = replace(
            first_pair.candidate,
            greptile=GreptileEvidence(
                status=EvaluatorStatus.COMPLETED, findings=(critical,)
            ),
        )
        second_candidate = replace(
            second_pair.candidate,
            greptile=GreptileEvidence(status=EvaluatorStatus.UNAVAILABLE, findings=()),
        )
        evidence = replace(
            self.evidence,
            pairs=(
                replace(first_pair, candidate=first_candidate),
                replace(second_pair, candidate=second_candidate),
            ),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertIn(ReasonCode.CRITICAL_FINDING, report.reason_codes)
        self.assertEqual(report.gate_results[2].status, GateStatus.NOT_EVALUATED)

    def test_forbidden_side_effect_rejects_regardless_of_efficiency(self) -> None:
        pair = self.evidence.pairs[0]
        candidate = replace(pair.candidate, policy_violations=("secret_leak",))
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertIn(ReasonCode.FORBIDDEN_SIDE_EFFECT, report.reason_codes)

    def test_reliability_regression_rejects(self) -> None:
        pair = self.evidence.pairs[1]
        candidate = replace(pair.candidate, execution_status=ExecutionStatus.TIMEOUT)
        evidence = replace(
            self.evidence,
            pairs=(self.evidence.pairs[0], replace(pair, candidate=candidate)),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertIn(ReasonCode.RELIABILITY_REGRESSION, report.reason_codes)

    def test_segment_reliability_regression_cannot_hide_in_overall_rate(self) -> None:
        pair = self.evidence.pairs[0]
        candidate = replace(pair.candidate, execution_status=ExecutionStatus.TIMEOUT)
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )
        config = replace(
            self.config,
            maximum_candidate_failure_rate=0.5,
            maximum_failure_rate_regression=0.5,
        )

        report = evaluate_policy(evidence, config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        reliability = report.gate_results[3]
        self.assertTrue(
            any(
                observation.metric == "segment.bug_fixing.execution_failure_rate"
                and observation.observed == 1.0
                for observation in reliability.observations
            )
        )

    def test_deterministic_quality_regression_rejects_with_clean_greptile(self) -> None:
        pair = self.evidence.pairs[1]
        candidate = replace(
            pair.candidate, deterministic_result=DeterministicResult.FAILED
        )
        evidence = replace(
            self.evidence,
            pairs=(self.evidence.pairs[0], replace(pair, candidate=candidate)),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertIn(ReasonCode.QUALITY_REGRESSION, report.reason_codes)

    def test_greptile_finding_shared_with_baseline_is_not_a_regression(self) -> None:
        pair = self.evidence.pairs[0]
        shared_finding = GreptileFinding(
            finding_id="candidate-medium-equivalent",
            severity=FindingSeverity.MEDIUM,
            category="maintainability",
            file_path="demo/file_a.py",
        )
        candidate = replace(
            pair.candidate,
            greptile=GreptileEvidence(
                status=EvaluatorStatus.COMPLETED, findings=(shared_finding,)
            ),
        )
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.PROMOTE)

    def test_high_severity_greptile_regression_rejects(self) -> None:
        pair = self.evidence.pairs[0]
        high_finding = GreptileFinding(
            finding_id="candidate-high-1",
            severity=FindingSeverity.HIGH,
            category="correctness",
            file_path="demo/file_a.py",
        )
        candidate = replace(
            pair.candidate,
            greptile=GreptileEvidence(
                status=EvaluatorStatus.COMPLETED, findings=(high_finding,)
            ),
        )
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertIn(ReasonCode.QUALITY_REGRESSION, report.reason_codes)

    def test_segment_quality_regression_cannot_hide_in_overall_average(self) -> None:
        pair = self.evidence.pairs[1]
        candidate = replace(
            pair.candidate, deterministic_result=DeterministicResult.FAILED
        )
        evidence = replace(
            self.evidence,
            pairs=(self.evidence.pairs[0], replace(pair, candidate=candidate)),
        )
        config = replace(
            self.config,
            quality_non_inferiority_margin=0.5,
            human_review_on_evaluator_conflict=False,
        )

        report = evaluate_policy(evidence, config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        quality = report.gate_results[4]
        self.assertTrue(
            any(
                observation.metric == "segment.testing.deterministic_pass_rate_delta"
                and observation.observed == -1.0
                for observation in quality.observations
            )
        )

    def test_efficiency_regression_rejects_after_quality_passes(self) -> None:
        pair = self.evidence.pairs[0]
        metrics = replace(
            pair.candidate.metrics,
            duration_ms=3000,
            total_tokens=3000,
            tool_call_count=12,
            estimated_cost_usd=0.3,
        )
        candidate = replace(pair.candidate, metrics=metrics)
        evidence = replace(
            self.evidence,
            pairs=(replace(pair, candidate=candidate), self.evidence.pairs[1]),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertEqual(report.gate_results[4].status, GateStatus.PASSED)
        self.assertIn(ReasonCode.EFFICIENCY_GUARDRAIL_FAILED, report.reason_codes)
        self.assertIn(ReasonCode.OBJECTIVE_NOT_MET, report.reason_codes)

    def test_objective_threshold_comes_from_policy_configuration(self) -> None:
        config = replace(self.config, minimum_objective_improvement=0.2)

        report = evaluate_policy(self.evidence, config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        self.assertIn(ReasonCode.OBJECTIVE_NOT_MET, report.reason_codes)
        self.assertNotIn(ReasonCode.EFFICIENCY_GUARDRAIL_FAILED, report.reason_codes)
        objective = next(
            observation
            for observation in report.gate_results[5].observations
            if observation.metric == "objective.total_tokens.improvement"
        )
        self.assertEqual(objective.threshold, 0.2)

    def test_single_pair_efficiency_regression_cannot_hide_in_aggregate(self) -> None:
        guardrail = next(
            item
            for item in self.config.efficiency_guardrails
            if item.metric is MetricName.TOTAL_TOKENS
        )
        first_pair, second_pair = self.evidence.pairs
        first_candidate = replace(
            first_pair.candidate,
            metrics=replace(first_pair.candidate.metrics, total_tokens=1400),
        )
        second_candidate = replace(
            second_pair.candidate,
            metrics=replace(second_pair.candidate.metrics, total_tokens=960),
        )
        evidence = replace(
            self.evidence,
            objective=None,
            pairs=(
                replace(first_pair, candidate=first_candidate),
                replace(second_pair, candidate=second_candidate),
            ),
        )
        config = replace(
            self.config, efficiency_guardrails=(guardrail,), require_objective=False
        )

        report = evaluate_policy(evidence, config)

        self.assertEqual(report.action, DecisionAction.REJECT)
        efficiency = report.gate_results[5]
        self.assertTrue(
            any(
                observation.metric
                == "segment.bug_fixing.total_tokens.candidate_to_baseline_ratio"
                and observation.observed == 1.4
                for observation in efficiency.observations
            )
        )

    def test_conflicting_valid_evaluators_request_human_review(self) -> None:
        pair = self.evidence.pairs[0]
        baseline = replace(
            pair.baseline,
            deterministic_result=DeterministicResult.FAILED,
            greptile=GreptileEvidence(status=EvaluatorStatus.COMPLETED, findings=()),
        )
        medium_finding = GreptileFinding(
            finding_id="candidate-medium-1",
            severity=FindingSeverity.MEDIUM,
            category="maintainability",
            file_path="demo/file_a.py",
        )
        candidate = replace(
            pair.candidate,
            greptile=GreptileEvidence(
                status=EvaluatorStatus.COMPLETED, findings=(medium_finding,)
            ),
        )
        evidence = replace(
            self.evidence,
            pairs=(
                replace(pair, baseline=baseline, candidate=candidate),
                self.evidence.pairs[1],
            ),
        )

        report = evaluate_policy(evidence, self.config)

        self.assertEqual(report.action, DecisionAction.HUMAN_REVIEW)
        self.assertIn(ReasonCode.EVALUATOR_CONFLICT, report.reason_codes)
        self.assertIn(ReasonCode.MANUAL_REVIEW_REQUIRED, report.reason_codes)

    def test_exact_quality_threshold_is_inclusive(self) -> None:
        pair = self.evidence.pairs[1]
        candidate = replace(
            pair.candidate, deterministic_result=DeterministicResult.FAILED
        )
        evidence = replace(
            self.evidence,
            pairs=(self.evidence.pairs[0], replace(pair, candidate=candidate)),
        )
        config = replace(
            self.config,
            quality_non_inferiority_margin=1.0,
            human_review_on_evaluator_conflict=False,
        )

        report = evaluate_policy(evidence, config)

        self.assertEqual(report.action, DecisionAction.PROMOTE)

    def test_exact_efficiency_threshold_is_inclusive(self) -> None:
        guardrail = next(
            item
            for item in self.config.efficiency_guardrails
            if item.metric is MetricName.TOTAL_TOKENS
        )
        first_pair, second_pair = self.evidence.pairs
        first_candidate = replace(
            first_pair.candidate,
            metrics=replace(first_pair.candidate.metrics, total_tokens=1200),
        )
        second_candidate = replace(
            second_pair.candidate,
            metrics=replace(second_pair.candidate.metrics, total_tokens=1440),
        )
        evidence = replace(
            self.evidence,
            objective=None,
            pairs=(
                replace(first_pair, candidate=first_candidate),
                replace(second_pair, candidate=second_candidate),
            ),
        )
        config = replace(
            self.config, efficiency_guardrails=(guardrail,), require_objective=False
        )

        report = evaluate_policy(evidence, config)

        self.assertEqual(report.action, DecisionAction.PROMOTE)

    def test_contract_validation_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ContractError, "unsupported evidence schema version"
        ):
            evaluate_policy(
                replace(self.evidence, schema_version="agentcd.evaluation.evidence/v2"),
                self.config,
            )
        with self.assertRaisesRegex(ContractError, "unsupported policy version"):
            evaluate_policy(
                self.evidence, replace(self.config, policy_version="offline-v2")
            )
        empty_requirement = replace(self.config.required_evaluators[0], evaluators=())
        with self.assertRaisesRegex(ContractError, "evaluators must not be empty"):
            evaluate_policy(
                self.evidence,
                replace(
                    self.config,
                    required_evaluators=(
                        empty_requirement,
                        *self.config.required_evaluators[1:],
                    ),
                ),
            )


def load_json(name: str) -> object:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def serialized(value: object) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def replace_json_value(document: object, path: list[object], value: object) -> None:
    if not path:
        raise AssertionError("replacement path must not be empty")
    target = document
    for part in path[:-1]:
        target = json_child(target, part)

    final_part = path[-1]
    if isinstance(target, dict) and isinstance(final_part, str):
        target[final_part] = value
        return
    if isinstance(target, list) and isinstance(final_part, int):
        target[final_part] = value
        return
    raise AssertionError(f"invalid replacement target: {path}")


def json_child(value: object, part: object) -> object:
    if isinstance(value, dict) and isinstance(part, str):
        return value[part]
    if isinstance(value, list) and isinstance(part, int):
        return value[part]
    raise AssertionError(f"invalid JSON path component: {part}")


def require_object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise AssertionError(f"{path} contains a non-string key")
        result[key] = item
    return result


def require_array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise AssertionError(f"{path} must be an array")
    return list(value)


def require_string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"{path} must be a string")
    return value


if __name__ == "__main__":
    unittest.main()
