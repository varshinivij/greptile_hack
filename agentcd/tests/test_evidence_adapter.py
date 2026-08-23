from __future__ import annotations

import unittest

from agentcd_bench.evaluation.models import (
    EvaluatorStatus,
    FindingSeverity,
    OutputType,
)
from agentcd_bench.evidence_adapter import (
    EvidenceAdapterError,
    build_evaluation_evidence,
)


class EvidenceAdapterTest(unittest.TestCase):
    def test_maps_a_to_candidate_b_to_baseline_and_normalizes_findings(self) -> None:
        evidence = build_evaluation_evidence(
            raw_evaluations=[evaluation_pair(candidate_severity="P0")],
            candidate_attempts=[attempt("candidate-commit")],
            baseline_attempts=[attempt("baseline-commit")],
            candidate_version="candidate-agents",
            baseline_version="baseline-agents",
            candidate_source_revision="shared-source",
            baseline_source_revision="shared-source",
            prompt_hash="prompt-sha",
            task_id="task-1",
            suite_version="suite/v1",
            segment="general",
            output_type=OutputType.CODE,
            runner="codex-cli/v1",
            tool_policy="workspace-write/v1",
        )

        pair = evidence.pairs[0]
        self.assertEqual(pair.candidate.attempt_id, "candidate-candidate-commit")
        self.assertEqual(pair.baseline.attempt_id, "baseline-baseline-commit")
        self.assertEqual(
            pair.candidate.greptile.findings[0].severity,
            FindingSeverity.CRITICAL,
        )
        self.assertEqual(pair.candidate.metrics.total_tokens, 120)
        self.assertEqual(evidence.observation_duration_seconds, 1.5)

    def test_failed_or_malformed_greptile_output_becomes_unavailable(self) -> None:
        raw = evaluation_pair()
        evaluations = raw["result"]["evaluations"]
        evaluations["a"] = {
            "status": "success",
            "commit_id": "candidate-commit",
            "greptile_output": {"unexpected": []},
        }
        evaluations["b"] = {
            "status": "failure",
            "commit_id": "baseline-commit",
            "error": "review failed",
        }

        evidence = build_evaluation_evidence(
            raw_evaluations=[raw],
            candidate_attempts=[attempt("candidate-commit")],
            baseline_attempts=[attempt("baseline-commit")],
            candidate_version="candidate-agents",
            baseline_version="baseline-agents",
            candidate_source_revision="shared-source",
            baseline_source_revision="shared-source",
            prompt_hash="prompt-sha",
            task_id="task-1",
            suite_version="suite/v1",
            segment="general",
            output_type=OutputType.CODE,
            runner="codex-cli/v1",
            tool_policy="workspace-write/v1",
        )

        self.assertEqual(
            evidence.pairs[0].candidate.greptile.status,
            EvaluatorStatus.UNAVAILABLE,
        )
        self.assertEqual(
            evidence.pairs[0].baseline.greptile.status,
            EvaluatorStatus.UNAVAILABLE,
        )

    def test_rejects_evaluator_result_for_the_wrong_attempt_commit(self) -> None:
        raw = evaluation_pair()
        raw["result"]["evaluations"]["a"]["commit_id"] = "wrong-commit"

        with self.assertRaisesRegex(EvidenceAdapterError, "does not match"):
            build_evaluation_evidence(
                raw_evaluations=[raw],
                candidate_attempts=[attempt("candidate-commit")],
                baseline_attempts=[attempt("baseline-commit")],
                candidate_version="candidate-agents",
                baseline_version="baseline-agents",
                candidate_source_revision="shared-source",
                baseline_source_revision="shared-source",
                prompt_hash="prompt-sha",
                task_id="task-1",
                suite_version="suite/v1",
                segment="general",
                output_type=OutputType.CODE,
                runner="codex-cli/v1",
                tool_policy="workspace-write/v1",
            )


def attempt(commit_id: str) -> dict[str, object]:
    return {
        "run_index": 1,
        "status": "success",
        "deterministic_result": "passed",
        "artifact": {"commit_id": commit_id},
        "llm_metrics": {
            "model": "codex-test",
            "duration_ms": 1500,
            "total_tokens": 120,
        },
        "tool_metrics": {"tool_call_count": 3},
    }


def evaluation_pair(candidate_severity: str = "P2") -> dict[str, object]:
    return {
        "run_index": 1,
        "result": {
            "evaluations": {
                "a": {
                    "status": "success",
                    "commit_id": "candidate-commit",
                    "greptile_output": {
                        "comments": [
                            {
                                "id": "candidate-finding",
                                "path": "src/auth.py",
                                "severity": candidate_severity,
                                "securityIssue": candidate_severity == "P0",
                                "category": "logic",
                            }
                        ]
                    },
                },
                "b": {
                    "status": "success",
                    "commit_id": "baseline-commit",
                    "greptile_output": {"comments": []},
                },
            }
        },
    }
