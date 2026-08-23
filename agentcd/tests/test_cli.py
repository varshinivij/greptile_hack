from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentcd_bench.cli import main
from agentcd_bench.codex_client import CodexExecRunner, parse_codex_jsonl
from agentcd_bench.metrics import percentile, summarize_attempts
from agentcd_bench.output import compact_result
from agentcd_bench.service import BenchmarkConfig, run_benchmark


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


class CodexJsonlParserTest(unittest.TestCase):
    def test_counts_command_execution_events(self) -> None:
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "ts": 10.0,
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "command": "rg layouts .",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "ts": 10.25,
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "command": "rg layouts .",
                            "status": "completed",
                            "exit_code": 0,
                            "aggregated_output": "layouts/baseof.html\n",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 40,
                            "output_tokens": 20,
                        },
                    }
                ),
            ]
        )

        parsed = parse_codex_jsonl(stdout)

        self.assertEqual(parsed["llm_metrics"]["total_tokens"], 120)
        self.assertEqual(parsed["tool_metrics"]["tool_call_count"], 1)
        self.assertEqual(parsed["tool_metrics"]["failed_tool_call_count"], 0)
        tool = parsed["tool_metrics"]["tool_calls"][0]
        self.assertEqual(tool["name"], "command_execution")
        self.assertEqual(tool["started_count"], 1)
        self.assertEqual(tool["completed_count"], 1)
        self.assertEqual(tool["duration_ms"], 250)
        self.assertEqual(tool["commands"], ["rg layouts ."])
        self.assertEqual(tool["output_chars"], len("layouts/baseof.html\n"))

    def test_counts_failed_command_execution(self) -> None:
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "command_execution",
                            "command": "false",
                            "status": "completed",
                            "exit_code": 1,
                            "aggregated_output": "",
                        },
                    }
                )
            ]
        )

        parsed = parse_codex_jsonl(stdout)

        self.assertEqual(parsed["tool_metrics"]["tool_call_count"], 1)
        self.assertEqual(parsed["tool_metrics"]["failed_tool_call_count"], 1)
        self.assertEqual(parsed["tool_metrics"]["tool_calls"][0]["failed_count"], 1)


class OutputTest(unittest.TestCase):
    def test_compact_result_truncates_long_command_samples(self) -> None:
        result = {
            "project": "/repo",
            "run_count": 1,
            "log_file": "/tmp/log.jsonl",
            "execution": {},
            "runs": [
                {
                    "version": "a",
                    "commit": "abc",
                    "worktree": None,
                    "summary": {},
                    "attempts": [
                        {
                            "run_index": 1,
                            "status": "success",
                            "returncode": 0,
                            "llm_metrics": {},
                            "tool_metrics": {
                                "tool_call_count": 7,
                                "tool_calls": [
                                    {
                                        "name": "command_execution",
                                        "commands": [f"cmd-{index}" for index in range(7)],
                                    }
                                ],
                            },
                            "git_diff": {
                                "changed_files": ["README.md"],
                                "stat": " README.md | 1 +\n",
                                "diff": "diff --git a/README.md b/README.md\n",
                            },
                            "raw_logs": {},
                        }
                    ],
                }
            ],
        }

        compact = compact_result(result)

        tool_call = compact["runs"][0]["attempts"][0]["tool_metrics"]["tool_calls"][0]
        self.assertEqual(tool_call["commands"], ["cmd-0", "cmd-1", "cmd-2", "cmd-3", "cmd-4"])
        self.assertEqual(tool_call["commands_truncated"], 2)
        git_diff = compact["runs"][0]["attempts"][0]["git_diff"]
        self.assertNotIn("diff", git_diff)
        self.assertTrue(git_diff["diff_truncated"])


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
                    "--log-file",
                    str(Path(temp) / "bench.jsonl"),
                ]
            )

            result = json.loads(output)
            self.assertEqual(result["run_count"], 2)
            self.assertEqual(len(result["runs"]), 2)
            self.assertEqual(len(result["runs"][0]["attempts"]), 2)
            self.assertEqual(result["runs"][0]["commit"], commit_a)
            self.assertEqual(result["runs"][1]["commit"], commit_b)
            self.assertIn("tool_call_count", result["runs"][0]["summary"])
            self.assertTrue(result["execution"]["version_runs_concurrent"])

    def test_cli_writes_debug_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            log_file = Path(temp) / "logs" / "run.jsonl"
            init_fixture_repo(project)

            output = capture_stdout(
                [
                    "--project",
                    str(project),
                    "--commit-a",
                    "HEAD",
                    "--commit-b",
                    "HEAD",
                    "--prompt",
                    "Do not write this raw prompt into logs.",
                    "--runs",
                    "1",
                    "--runner",
                    "mock",
                    "--json-only",
                    "--log-file",
                    str(log_file),
                ]
            )

            result = json.loads(output)
            actual_log_file = Path(result["log_file"])
            self.assertEqual(actual_log_file.parent, log_file.parent.resolve())
            self.assertTrue(actual_log_file.name.startswith("run-"))
            self.assertEqual(actual_log_file.suffix, ".jsonl")
            records = [json.loads(line) for line in actual_log_file.read_text(encoding="utf-8").splitlines()]
            events = [record["event"] for record in records]
            self.assertIn("cli_start", events)
            self.assertIn("worktrees_created", events)
            self.assertIn("attempt_start", events)
            self.assertIn("codex_invocation_logs", events)
            self.assertIn("attempt_git_diff", events)
            self.assertIn("attempt_metrics_parsed", events)
            self.assertIn("attempt_end", events)
            self.assertIn("summaries_created", events)
            self.assertIn("cli_end", events)

            cli_start = next(record for record in records if record["event"] == "cli_start")
            self.assertEqual(cli_start["prompt_source"], "inline")
            self.assertEqual(cli_start["prompt_chars"], 39)
            self.assertEqual(cli_start["level"], "info")
            self.assertNotIn("Do not write", actual_log_file.read_text(encoding="utf-8"))
            self.assertIn("<redacted>", cli_start["argv"])

            attempt = result["runs"][0]["attempts"][0]
            stdout_log = Path(attempt["raw_logs"]["stdout_jsonl"])
            stderr_log = Path(attempt["raw_logs"]["stderr"])
            self.assertTrue(stdout_log.exists())
            self.assertTrue(stderr_log.exists())
            self.assertTrue(stdout_log.name.endswith(".codex-a-run-1.stdout.jsonl"))
            self.assertTrue(stderr_log.name.endswith(".codex-a-run-1.stderr.log"))

    def test_cli_verbose_flag_is_logged_and_prints_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            log_file = Path(temp) / "logs" / "run.jsonl"
            init_fixture_repo(project)

            output = capture_stdout(
                [
                    "--project",
                    str(project),
                    "--commit-a",
                    "HEAD",
                    "--commit-b",
                    "HEAD",
                    "--prompt",
                    "Explain the codebase.",
                    "--runs",
                    "1",
                    "--runner",
                    "mock",
                    "--json-only",
                    "--verbose",
                    "--log-file",
                    str(log_file),
                ]
            )

            result = json.loads(output)
            actual_log_file = Path(result["log_file"])
            records = [json.loads(line) for line in actual_log_file.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(next(record for record in records if record["event"] == "cli_start")["verbose"])
            self.assertTrue(next(record for record in records if record["event"] == "cli_output_written")["verbose"])

    def test_attempt_log_includes_git_diff_when_runner_changes_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            log_file = Path(temp) / "run.jsonl"
            init_fixture_repo(project)

            result = run_benchmark(
                BenchmarkConfig(
                    project=project,
                    commit_a="HEAD",
                    commit_b="HEAD",
                    prompt="Change README.",
                    runs=1,
                    log_file=log_file,
                ),
                FileChangingRunner(),
            )

            self.assertEqual(result["runs"][0]["attempts"][0]["git_diff"]["changed_files"], ["README.md"])
            self.assertIn("+Generated change.", result["runs"][0]["attempts"][0]["git_diff"]["diff"])
            records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
            diff_events = [record for record in records if record["event"] == "attempt_git_diff"]
            self.assertEqual(len(diff_events), 2)
            self.assertIn("+Generated change.", diff_events[0]["diff"])
            self.assertEqual(diff_events[0]["changed_files"], ["README.md"])

    def test_attempt_log_includes_untracked_files_in_git_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            log_file = Path(temp) / "run.jsonl"
            init_fixture_repo(project)

            result = run_benchmark(
                BenchmarkConfig(
                    project=project,
                    commit_a="HEAD",
                    commit_b="HEAD",
                    prompt="Create a new file.",
                    runs=1,
                    log_file=log_file,
                ),
                UntrackedFileRunner(),
            )

            diff = result["runs"][0]["attempts"][0]["git_diff"]
            self.assertEqual(diff["changed_files"], ["NEW_FILE.md"])
            self.assertEqual(diff["name_status"], ["A\tNEW_FILE.md"])
            self.assertEqual(diff["status_porcelain"], ["?? NEW_FILE.md"])
            self.assertIn("new untracked content", diff["diff"])

            records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
            diff_event = next(record for record in records if record["event"] == "attempt_git_diff")
            self.assertIn("new untracked content", diff_event["diff"])
            self.assertEqual(diff_event["name_status"], ["A\tNEW_FILE.md"])


class OrchestrationTest(unittest.TestCase):
    def test_versions_run_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            init_fixture_repo(project)
            commit_a = git(project, "rev-parse", "HEAD").strip()
            write_file(project / "AGENTS.md", "# Agent B\n\nUse deeper repository analysis.\n")
            git(project, "add", "AGENTS.md")
            git(project, "commit", "-m", "agent b")
            commit_b = git(project, "rev-parse", "HEAD").strip()

            runner = OverlapDetectingRunner()
            result = run_benchmark(
                BenchmarkConfig(
                    project=project,
                    commit_a=commit_a,
                    commit_b=commit_b,
                    prompt="Explain the codebase.",
                    runs=1,
                ),
                runner,
            )

            self.assertEqual(len(result["runs"]), 2)
            self.assertGreaterEqual(runner.max_active, 2)

    def test_commits_outputs_calls_evaluator_and_cleans_temporary_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "repo"
            init_fixture_repo(project)
            starting_commit = git(project, "rev-parse", "HEAD").strip()
            response = {"evaluations": {"a": {"status": "success"}, "b": {"status": "success"}}}

            with patch(
                "agentcd_bench.service.EvaluationClient.evaluate_pair",
                return_value=response,
            ) as evaluate_pair:
                result = run_benchmark(
                    BenchmarkConfig(
                        project=project,
                        commit_a=starting_commit,
                        commit_b=starting_commit,
                        prompt="Rename the function.",
                        runs=1,
                        evaluator_url="http://127.0.0.1:8000",
                        base_branch="master",
                    ),
                    FileChangingRunner(),
                )

            payload = evaluate_pair.call_args.args[0]
            self.assertEqual(payload["repo"], str(project))
            self.assertEqual(payload["base_branch"], "master")
            self.assertNotEqual(payload["commit_a"], starting_commit)
            self.assertNotEqual(payload["commit_b"], starting_commit)
            self.assertEqual(result["evaluations"][0]["result"], response)
            self.assertTrue(result["runs"][0]["attempts"][0]["artifact"]["has_changes"])

            branches = git(project, "branch", "--list", "agentcd-eval/*")
            self.assertEqual(branches.strip(), "")


class CodexRunnerTest(unittest.TestCase):
    def test_codex_exec_uses_fresh_context_and_closed_stdin(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch("agentcd_bench.codex_client.subprocess.run", return_value=completed) as run:
            CodexExecRunner(command="codex", model="gpt-test").run(Path("/tmp/worktree"), "hello")

        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [
                "codex",
                "exec",
                "--json",
                "--ephemeral",
                "--sandbox",
                "workspace-write",
                "--cd",
                "/tmp/worktree",
                "--model",
                "gpt-test",
                "hello",
            ],
        )
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)


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


class OverlapDetectingRunner:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def run(self, cwd: Path, prompt: str, context: object | None = None) -> dict[str, object]:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.1)
            return {
                "status": "success",
                "llm_metrics": {
                    "model": "overlap-test",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "reasoning_tokens": 0,
                    "cached_input_tokens": 0,
                    "duration_ms": 100,
                },
                "tool_metrics": {
                    "tool_call_count": 0,
                    "tool_calls": [],
                },
                "returncode": 0,
            }
        finally:
            with self.lock:
                self.active -= 1


class FileChangingRunner:
    def run(self, cwd: Path, prompt: str, context: object | None = None) -> dict[str, object]:
        readme = cwd / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nGenerated change.\n", encoding="utf-8")
        return {
            "status": "success",
            "llm_metrics": {
                "model": "file-changing-test",
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "reasoning_tokens": 0,
                "cached_input_tokens": 0,
                "duration_ms": 100,
            },
            "tool_metrics": {
                "tool_call_count": 0,
                "tool_calls": [],
            },
            "returncode": 0,
        }


class UntrackedFileRunner:
    def run(self, cwd: Path, prompt: str, context: object | None = None) -> dict[str, object]:
        (cwd / "NEW_FILE.md").write_text("new untracked content\n", encoding="utf-8")
        return {
            "status": "success",
            "llm_metrics": {
                "model": "untracked-file-test",
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "reasoning_tokens": 0,
                "cached_input_tokens": 0,
                "duration_ms": 100,
            },
            "tool_metrics": {
                "tool_call_count": 0,
                "tool_calls": [],
            },
            "returncode": 0,
        }


if __name__ == "__main__":
    unittest.main()
