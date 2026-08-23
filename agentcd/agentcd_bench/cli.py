from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .codex_client import CodexExecRunner, MockCodexRunner
from .output import comparison_table
from .service import BenchmarkConfig, run_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents-bench",
        description="Compare Codex metrics across two committed AGENTS.md versions.",
    )
    parser.add_argument("--project", required=True, help="Path to the git repository to benchmark.")
    parser.add_argument("--commit-a", help="Commit hash for version A. Defaults to project HEAD.")
    parser.add_argument("--commit-b", help="Commit hash for version B. Defaults to master.")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Prompt text to run in both worktrees.")
    prompt_group.add_argument("--prompt-file", help="File containing the prompt to run.")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per version. Default: 1.")
    parser.add_argument("--model", help="Optional Codex model name.")
    parser.add_argument("--keep-worktrees", action="store_true", help="Keep temp worktrees after the run.")
    parser.add_argument("--json-only", action="store_true", help="Only print JSON, without the comparison table.")
    parser.add_argument(
        "--log-file",
        help="Path for JSONL trace logs. Defaults to logs/agents-bench-<timestamp>.jsonl.",
    )
    parser.add_argument(
        "--runner",
        choices=["codex", "mock"],
        default="codex",
        help="Execution backend. Use mock for local validation without Codex credentials.",
    )
    parser.add_argument("--codex-command", default="codex", help="Codex executable to invoke. Default: codex.")
    return parser


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    return Path(args.prompt_file).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    runner = (
        MockCodexRunner(model=args.model)
        if args.runner == "mock"
        else CodexExecRunner(command=args.codex_command, model=args.model)
    )

    config = BenchmarkConfig(
        project=Path(args.project).resolve(),
        commit_a=args.commit_a,
        commit_b=args.commit_b,
        prompt=read_prompt(args),
        runs=args.runs,
        keep_worktrees=args.keep_worktrees,
        log_file=resolve_log_file(args.log_file),
    )

    try:
        result = run_benchmark(config, runner)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    if not args.json_only:
        print()
        print(comparison_table(result))
    return 0


def resolve_log_file(log_file: str | None) -> Path:
    if log_file:
        return Path(log_file).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (Path.cwd() / "logs" / f"agents-bench-{timestamp}.jsonl").resolve()
