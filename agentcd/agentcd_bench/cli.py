from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .codex_client import CodexExecRunner, MockCodexRunner
from .output import comparison_table
from .service import BenchmarkConfig, run_benchmark
from .tracing import JsonlTraceLogger

DEFAULT_PROJECT = Path(__file__).resolve().parents[2] / "hugoDocs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents-bench",
        description="Compare Codex metrics across two committed AGENTS.md versions.",
    )
    parser.add_argument(
        "--project",
        default=str(DEFAULT_PROJECT),
        help=f"Repository or subdirectory to benchmark. Default: {DEFAULT_PROJECT}",
    )
    parser.add_argument("--commit-a", help="Commit hash for version A. Defaults to project HEAD.")
    parser.add_argument("--commit-b", help="Commit hash for version B. Defaults to main.")
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
    parser.add_argument(
        "--evaluator-url",
        help="FastAPI evaluator base URL, for example http://127.0.0.1:8000.",
    )
    parser.add_argument("--base-branch", default="main", help="Base branch passed to Greptile. Default: main.")
    parser.add_argument(
        "--evaluator-timeout",
        type=float,
        default=700.0,
        help="Evaluation service HTTP timeout in seconds. Default: 700.",
    )
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

    invocation_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = resolve_log_file(args.log_file, invocation_timestamp)
    logger = JsonlTraceLogger(log_file)
    prompt = read_prompt(args)
    prompt_source = "inline" if args.prompt is not None else str(Path(args.prompt_file).expanduser().resolve())
    logger.event(
        "cli_start",
        argv=sanitize_argv(argv if argv is not None else sys.argv[1:]),
        invocation_timestamp=invocation_timestamp,
        cwd=os.getcwd(),
        project=str(Path(args.project).resolve()),
        commit_a=args.commit_a,
        commit_b=args.commit_b,
        runs=args.runs,
        runner=args.runner,
        model=args.model,
        codex_command=args.codex_command if args.runner == "codex" else None,
        keep_worktrees=args.keep_worktrees,
        json_only=args.json_only,
        evaluator_url=args.evaluator_url,
        base_branch=args.base_branch,
        prompt_source=prompt_source,
        prompt_chars=len(prompt),
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        log_file=str(log_file),
    )

    runner = (
        MockCodexRunner(model=args.model)
        if args.runner == "mock"
        else CodexExecRunner(command=args.codex_command, model=args.model)
    )
    logger.event("runner_created", runner=args.runner, model=args.model)

    config = BenchmarkConfig(
        project=Path(args.project).resolve(),
        commit_a=args.commit_a,
        commit_b=args.commit_b,
        prompt=prompt,
        runs=args.runs,
        keep_worktrees=args.keep_worktrees,
        log_file=log_file,
        evaluator_url=args.evaluator_url,
        evaluator_timeout_seconds=args.evaluator_timeout,
        base_branch=args.base_branch,
    )

    try:
        result = run_benchmark(config, runner)
    except Exception as exc:
        logger.event("cli_error", error_type=type(exc).__name__, error=str(exc))
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    if not args.json_only:
        print()
        print(comparison_table(result))
    logger.event("cli_output_written", json_only=args.json_only)
    logger.event("cli_end", status="success")
    return 0


def resolve_log_file(log_file: str | None, timestamp: str | None = None) -> Path:
    timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if log_file:
        path = Path(log_file).expanduser()
        if path.suffix:
            path = path.with_name(f"{path.stem}-{timestamp}{path.suffix}")
        else:
            path = path / f"agents-bench-{timestamp}.jsonl"
        return path.resolve()
    return (Path.cwd() / "logs" / f"agents-bench-{timestamp}.jsonl").resolve()


def sanitize_argv(argv: list[str]) -> list[str]:
    sanitized = list(argv)
    for index, value in enumerate(sanitized):
        if value == "--prompt" and index + 1 < len(sanitized):
            sanitized[index + 1] = "<redacted>"
        elif value.startswith("--prompt="):
            sanitized[index] = "--prompt=<redacted>"
    return sanitized
