from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentcd_bench.cli import main
from agentcd_bench.metrics import percentile, summarize_attempts


class MetricsTest(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self) -> None:
        self.assertEqual(percentile([10, 20, 30, 40, 50], 50), 30)
        self.assertEqual(percentile([10, 20, 30, 40, 50], 90), 50)

    def test_summarize_attempts_includes_llm_and_tool_metrics(self) -> None:
        summary = summarize_attempts(
            [
                {"llm_metrics": {"total_tokens": 10, "duration_ms": 100}, "tool_metrics": {"tool_call_count": 2}},
                {"llm_metrics": {"total_tokens": 30, "duration_ms": 200}, "tool_metrics": {"tool_call_count": 4}},
            ]
        )

        self.assertEqual(summary["total_tokens"]["avg"], 20)
        self.assertEqual(summary["total_tokens"]["p50"], 10)
        self.assertEqual(summary["duration_ms"]["p90"], 200)
        self.assertEqual(summary["tool_call_count"]["avg"], 3)


class CliTest(unittest.TestCase):
    def test_cli_runs_against_two_commits_with_mock_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            init_fixture_repo(project)
            commit_a = git(project, "rev-parse", "HEAD").strip()
            write_file(project / "AGENTS.md", "# Agent B\n\nUse deeper repository analysis.\n")
            git(project, "add", "AGENTS.md")
            git(project, "commit", "-m", "agent b")
            commit_b = git(project, "rev-parse", "HEAD").strip()

            output = capture_stdout(
                [
                    "--project",
                    str(project),
                    "--commit-a",
                    commit_a,
                    "--commit-b",
                    commit_b,
                    "--prompt",
                    "Explain the codebase.",
                    "--runs",
                    "2",
                    "--runner",
                    "mock",
                    "--json-only",
                ]
            )

            result = json.loads(output)
            self.assertEqual(result["run_count"], 2)
            self.assertEqual(len(result["runs"]), 2)
            self.assertEqual(len(result["runs"][0]["attempts"]), 2)
            self.assertEqual(result["runs"][0]["commit"], commit_a)
            self.assertEqual(result["runs"][1]["commit"], commit_b)
            self.assertIn("tool_call_count", result["runs"][0]["summary"])


def init_fixture_repo(project: Path) -> None:
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "test@example.com")
    git(project, "config", "user.name", "Test User")
    write_file(project / "AGENTS.md", "# Agent A\n\nUse local conventions.\n")
    write_file(project / "README.md", "# Fixture\n")
    git(project, "add", "AGENTS.md", "README.md")
    git(project, "commit", "-m", "agent a")
    git(project, "branch", "master")


def write_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def git(project: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(project), *args], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc.stdout


def capture_stdout(args: list[str]) -> str:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = main(args)
    if exit_code != 0:
        raise AssertionError(f"CLI exited with {exit_code}")
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
