from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .codex_client import CodexExecRunner, MockCodexRunner
from .evaluation import ContractError, parse_policy_config
from .evaluation.models import ObjectiveMetric, OutputType
from .output import compact_result, comparison_table, verbose_result
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
    parser.add_argument("--verbose", action="store_true", help="Print full verbose JSON, including per-attempt details.")
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
    parser.add_argument(
        "--policy-config",
        help="Policy configuration JSON. Requires --evaluator-url and enables a decision.",
    )
    parser.add_argument("--task-id", default="ad-hoc-task", help="Task identifier used in policy evidence.")
    parser.add_argument(
        "--suite-version",
        default="ad-hoc-suite/v1",
        help="Task-suite version used in policy evidence.",
    )
    parser.add_argument("--segment", default="general", help="Task segment used in policy evidence.")
    parser.add_argument(
        "--output-type",
        choices=[value.value for value in OutputType],
        default=OutputType.CODE.value,
        help="Task output type used to select required evaluators. Default: code.",
    )
    parser.add_argument(
        "--objective",
        choices=[value.value for value in ObjectiveMetric],
        help="Optional candidate objective metric.",
    )
    parser.add_argument(
        "--decision-report",
        help="Markdown decision path. Defaults beside the trace log when policy evaluation is enabled.",
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
    if args.policy_config and not args.evaluator_url:
        parser.error("--policy-config requires --evaluator-url")
    if args.decision_report and not args.policy_config:
        parser.error("--decision-report requires --policy-config")

    policy_config = None
    if args.policy_config:
        try:
            policy_payload = json.loads(
                Path(args.policy_config).read_text(encoding="utf-8")
            )
            policy_config = parse_policy_config(policy_payload)
        except (OSError, json.JSONDecodeError, ContractError) as exc:
            parser.error(f"cannot load --policy-config: {exc}")

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
        verbose=args.verbose,
        prompt_source=prompt_source,
        prompt_chars=len(prompt),
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        log_file=str(log_file),
        policy_config=args.policy_config,
        task_id=args.task_id,
        suite_version=args.suite_version,
        segment=args.segment,
        output_type=args.output_type,
        objective=args.objective,
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
        policy_config=policy_config,
        task_id=args.task_id,
        suite_version=args.suite_version,
        segment=args.segment,
        output_type=OutputType(args.output_type),
        objective_metric=ObjectiveMetric(args.objective) if args.objective else None,
        runner_id="mock-codex/v1" if args.runner == "mock" else "codex-cli/v1",
        tool_policy="mock-read/v1" if args.runner == "mock" else "workspace-write/v1",
    )

    try:
        result = run_benchmark(config, runner)
    except Exception as exc:
        logger.event("cli_error", error_type=type(exc).__name__, error=str(exc))
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    decision_markdown = result.pop("decision_markdown", None)
    if isinstance(decision_markdown, str):
        report_path = resolve_decision_report(args.decision_report, log_file)
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(decision_markdown, encoding="utf-8")
        except OSError as exc:
            result["decision_report"] = {
                "status": "failure",
                "path": str(report_path),
                "error": str(exc),
            }
            logger.event("decision_report_error", path=str(report_path), error=str(exc))
        else:
            result["decision_report"] = {
                "status": "written",
                "path": str(report_path),
            }
            logger.event("decision_report_written", path=str(report_path))

    output_result = verbose_result(result) if args.verbose else compact_result(result)
    print(json.dumps(output_result, indent=2))
    if not args.json_only:
        print()
        print(comparison_table(result))
    logger.event("cli_output_written", json_only=args.json_only, verbose=args.verbose)
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


def resolve_decision_report(report_file: str | None, log_file: Path) -> Path:
    if report_file:
        return Path(report_file).expanduser().resolve()
    return log_file.with_name(f"{log_file.stem}.decision.md")


def sanitize_argv(argv: list[str]) -> list[str]:
    sanitized = list(argv)
    for index, value in enumerate(sanitized):
        if value == "--prompt" and index + 1 < len(sanitized):
            sanitized[index + 1] = "<redacted>"
        elif value.startswith("--prompt="):
            sanitized[index] = "--prompt=<redacted>"
    return sanitized
