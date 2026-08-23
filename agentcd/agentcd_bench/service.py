from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .codex_client import Runner
from .git_worktrees import WorktreeManager
from .metrics import summarize_attempts
from .tracing import JsonlTraceLogger


@dataclass(frozen=True)
class BenchmarkConfig:
    project: Path
    commit_a: str | None
    commit_b: str | None
    prompt: str
    runs: int = 1
    keep_worktrees: bool = False
    log_file: Path | None = None


def run_benchmark(config: BenchmarkConfig, runner: Runner) -> dict[str, Any]:
    logger = JsonlTraceLogger(config.log_file)
    logger.event(
        "benchmark_start",
        project=str(config.project),
        commit_a=config.commit_a,
        commit_b=config.commit_b,
        runs=config.runs,
    )
    with WorktreeManager(
        project=config.project,
        commit_a=config.commit_a,
        commit_b=config.commit_b,
        keep=config.keep_worktrees,
    ) as worktrees:
        logger.event(
            "worktrees_created",
            commit_a=worktrees.commit_a,
            commit_b=worktrees.commit_b,
            path_a=str(worktrees.path_a),
            path_b=str(worktrees.path_b),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(run_attempts, runner, worktrees.path_a, config.prompt, config.runs, "a", logger)
            future_b = executor.submit(run_attempts, runner, worktrees.path_b, config.prompt, config.runs, "b", logger)
            attempts_a = future_a.result()
            attempts_b = future_b.result()

        result = {
            "project": str(config.project),
            "run_count": config.runs,
            "log_file": str(config.log_file) if config.log_file else None,
            "execution": {
                "version_runs_concurrent": True,
                "runs_within_version": "sequential",
            },
            "runs": [
                {
                    "version": "a",
                    "commit": worktrees.commit_a,
                    "worktree": str(worktrees.path_a) if config.keep_worktrees else None,
                    "attempts": attempts_a,
                    "summary": summarize_attempts(attempts_a),
                },
                {
                    "version": "b",
                    "commit": worktrees.commit_b,
                    "worktree": str(worktrees.path_b) if config.keep_worktrees else None,
                    "attempts": attempts_b,
                    "summary": summarize_attempts(attempts_b),
                },
            ],
        }
        logger.event("benchmark_end", status="success")
        return result


def run_attempts(
    runner: Runner,
    cwd: Path,
    prompt: str,
    runs: int,
    version: str,
    logger: JsonlTraceLogger,
) -> list[dict[str, Any]]:
    logger.event("version_start", version=version, cwd=str(cwd), runs=runs)
    attempts = []
    for run_index in range(1, runs + 1):
        logger.event("attempt_start", version=version, run_index=run_index, cwd=str(cwd))
        attempt = runner.run(cwd=cwd, prompt=prompt)
        attempt["run_index"] = run_index
        logger.event(
            "attempt_end",
            version=version,
            run_index=run_index,
            cwd=str(cwd),
            status=attempt.get("status"),
            total_tokens=attempt.get("llm_metrics", {}).get("total_tokens"),
            duration_ms=attempt.get("llm_metrics", {}).get("duration_ms"),
            tool_call_count=attempt.get("tool_metrics", {}).get("tool_call_count"),
        )
        attempts.append(attempt)
    logger.event("version_end", version=version, cwd=str(cwd), runs=runs)
    return attempts
