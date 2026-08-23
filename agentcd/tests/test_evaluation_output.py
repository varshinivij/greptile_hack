from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agentcd_bench.evaluation import (
    decision_report_markdown,
    evaluate_policy_payload,
)
from agentcd_bench.evaluation_cli import main


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evaluation"


class DecisionOutputTest(unittest.TestCase):
    def test_markdown_contains_decision_gates_observations_and_coverage(self) -> None:
        report = evaluate_policy_payload(
            load_json("healthy_evidence.json"),
            load_json("offline_policy.json"),
        )

        rendered = decision_report_markdown(report)

        self.assertIn("# AgentCD Decision: ✅ PROMOTE", rendered)
        self.assertIn("`candidate-agents-v2`", rendered)
        self.assertIn("| `safety` | ✅ passed |", rendered)
        self.assertIn("`candidate_critical_finding_count`", rendered)
        self.assertIn("**Coverage:** 2 paired samples", rendered)
        self.assertIn("Decision schema `agentcd.evaluation.decision/v1`", rendered)

    def test_cli_writes_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "decision.md"

            exit_code = main(
                [
                    "--evidence",
                    str(FIXTURE_ROOT / "healthy_evidence.json"),
                    "--policy",
                    str(FIXTURE_ROOT / "offline_policy.json"),
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.read_text(encoding="utf-8").startswith("# AgentCD Decision"))

    def test_cli_can_print_canonical_json(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "--evidence",
                    str(FIXTURE_ROOT / "healthy_evidence.json"),
                    "--policy",
                    str(FIXTURE_ROOT / "offline_policy.json"),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["action"], "promote")


def load_json(name: str) -> object:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
