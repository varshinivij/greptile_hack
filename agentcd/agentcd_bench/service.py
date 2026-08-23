from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .codex_client import Runner
from .evaluator_client import EvaluationClient
from .git_worktrees import WorktreeManager, git
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
    evaluator_url: str | None = None
    evaluator_timeout_seconds: float = 700.0
    base_branch: str = "main"


def run_benchmark(config: BenchmarkConfig, runner: Runner) -> dict[str, Any]:
    logger = JsonlTraceLogger(config.log_file)
    logger.event(
        "benchmark_start",
        project=str(config.project),
        commit_a=config.commit_a,
        commit_b=config.commit_b,
        runs=config.runs,
    )
    logger.event("worktree_setup_start", level="debug", project=str(config.project), keep_worktrees=config.keep_worktrees)
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
        logger.event("concurrent_versions_start", level="debug", max_workers=2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            logger.event("version_submitted", level="debug", version="a", cwd=str(worktrees.path_a), runs=config.runs)
            future_a = executor.submit(
                run_attempts,
                runner,
                worktrees.path_a,
                worktrees.commit_a,
                config.prompt,
                config.runs,
                "a",
                logger,
                bool(config.evaluator_url),
            )
            logger.event("version_submitted", level="debug", version="b", cwd=str(worktrees.path_b), runs=config.runs)
            future_b = executor.submit(
                run_attempts,
                runner,
                worktrees.path_b,
                worktrees.commit_b,
                config.prompt,
                config.runs,
                "b",
                logger,
                bool(config.evaluator_url),
            )
            attempts_a = future_a.result()
            logger.event("version_result_collected", level="debug", version="a", attempts=len(attempts_a))
            attempts_b = future_b.result()
            logger.event("version_result_collected", level="debug", version="b", attempts=len(attempts_b))
        logger.event("concurrent_versions_end", level="debug")

        summary_a = summarize_attempts(attempts_a)
        summary_b = summarize_attempts(attempts_b)
        logger.event(
            "summaries_created",
            level="debug",
            version_a_fields=sorted(summary_a.keys()),
            version_b_fields=sorted(summary_b.keys()),
        )

        evaluations: list[dict[str, Any]] = []
        temporary_branches = [
            attempt["artifact"]["branch"]
            for attempt in attempts_a + attempts_b
            if attempt.get("artifact", {}).get("branch")
        ]
        try:
            if config.evaluator_url:
                client = EvaluationClient(config.evaluator_url, config.evaluator_timeout_seconds)
                for attempt_a, attempt_b in zip(attempts_a, attempts_b, strict=True):
                    artifact_a = attempt_a["artifact"]
                    artifact_b = attempt_b["artifact"]
                    payload = {
                        "repo": str(config.project),
                        "base_branch": config.base_branch,
                        "branch_a": artifact_a["branch"],
                        "commit_a": artifact_a["commit_id"],
                        "branch_b": artifact_b["branch"],
                        "commit_b": artifact_b["commit_id"],
                    }
                    logger.event("evaluation_request_start", run_index=attempt_a["run_index"], **payload)
                    evaluation = client.evaluate_pair(payload)
                    evaluations.append({"run_index": attempt_a["run_index"], "result": evaluation})
                    logger.event(
                        "evaluation_request_end",
                        run_index=attempt_a["run_index"],
                        status=evaluation.get("status", "success"),
                    )

            result = {
                "project": str(config.project),
                "run_count": config.runs,
                "log_file": str(config.log_file) if config.log_file else None,
                "execution": {
                    "version_runs_concurrent": True,
                    "runs_within_version": "sequential",
                    "evaluation_service": config.evaluator_url,
                },
                "evaluations": evaluations,
                "runs": [
                    {
                        "version": "a",
                        "commit": worktrees.commit_a,
                        "worktree": str(worktrees.path_a) if config.keep_worktrees else None,
                        "attempts": attempts_a,
                        "summary": summary_a,
                    },
                    {
                        "version": "b",
                        "commit": worktrees.commit_b,
                        "worktree": str(worktrees.path_b) if config.keep_worktrees else None,
                        "attempts": attempts_b,
                        "summary": summary_b,
                    },
                ],
            }
            logger.event("result_created", level="debug", run_count=config.runs, versions=2)
            logger.event("benchmark_end", status="success")
            return result
        finally:
            for branch in temporary_branches:
                try:
                    git(config.project, "branch", "-D", branch)
                except RuntimeError as exc:
                    logger.event("evaluation_branch_cleanup_error", branch=branch, error=str(exc))


def run_attempts(
    runner: Runner,
    cwd: Path,
    starting_commit: str,
    prompt: str,
    runs: int,
    version: str,
    logger: JsonlTraceLogger,
    capture_artifact: bool = False,
) -> list[dict[str, Any]]:
    logger.event("version_start", version=version, cwd=str(cwd), runs=runs)
    attempts = []
    for run_index in range(1, runs + 1):
        if capture_artifact:
            git(cwd, "reset", "--hard", starting_commit)
            git(cwd, "clean", "-fd")
        logger.event("attempt_start", version=version, run_index=run_index, cwd=str(cwd))
        attempt = runner.run(cwd=cwd, prompt=prompt)
        attempt["run_index"] = run_index
        if capture_artifact:
            attempt["artifact"] = commit_attempt(cwd, version, run_index)
        logger.event(
            "attempt_metrics_parsed",
            level="debug",
            version=version,
            run_index=run_index,
            status=attempt.get("status"),
            input_tokens=attempt.get("llm_metrics", {}).get("input_tokens"),
            output_tokens=attempt.get("llm_metrics", {}).get("output_tokens"),
            total_tokens=attempt.get("llm_metrics", {}).get("total_tokens"),
            cached_input_tokens=attempt.get("llm_metrics", {}).get("cached_input_tokens"),
            tool_call_count=attempt.get("tool_metrics", {}).get("tool_call_count"),
            returncode=attempt.get("returncode"),
        )
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


def commit_attempt(cwd: Path, version: str, run_index: int) -> dict[str, Any]:
    changed_files = [line for line in git(cwd, "status", "--porcelain").splitlines() if line]
    git(cwd, "add", "-A")
    patch = git(cwd, "diff", "--cached", "--binary")
    git(
        cwd,
        "-c",
        "user.name=AgentCD Evaluator",
        "-c",
        "user.email=agentcd-evaluator@localhost",
        "commit",
        "--allow-empty",
        "-m",
        f"AgentCD evaluation {version} attempt {run_index}",
    )
    commit_id = git(cwd, "rev-parse", "HEAD").strip()
    branch = f"agentcd-eval/{uuid4().hex}/{version}-{run_index}"
    git(cwd, "branch", branch, commit_id)
    return {
        "branch": branch,
        "commit_id": commit_id,
        "patch": patch,
        "changed_files": changed_files,
        "has_changes": bool(changed_files),
    }
