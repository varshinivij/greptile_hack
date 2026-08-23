from __future__ import annotations

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .codex_client import RunContext, Runner
from .evaluation.models import ObjectiveMetric, OutputType, PolicyConfig
from .evaluation.output import decision_report_markdown
from .evaluation.policy import evaluate_policy
from .evidence_adapter import build_evaluation_evidence
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
    policy_config: PolicyConfig | None = None
    task_id: str = "ad-hoc-task"
    suite_version: str = "ad-hoc-suite/v1"
    segment: str = "general"
    output_type: OutputType = OutputType.CODE
    objective_metric: ObjectiveMetric | None = None
    runner_id: str = "unknown-runner"
    tool_policy: str = "unknown-tool-policy"


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

            evidence_payload = None
            decision_payload = None
            decision_markdown = None
            if config.policy_config:
                if not evaluations:
                    raise ValueError(
                        "policy evaluation requires raw Greptile evaluations"
                    )
                candidate_source, baseline_source = resolve_source_revisions(
                    config.project,
                    worktrees.commit_a,
                    worktrees.commit_b,
                )
                evidence = build_evaluation_evidence(
                    raw_evaluations=evaluations,
                    candidate_attempts=attempts_a,
                    baseline_attempts=attempts_b,
                    candidate_version=worktrees.commit_a,
                    baseline_version=worktrees.commit_b,
                    candidate_source_revision=candidate_source,
                    baseline_source_revision=baseline_source,
                    prompt_hash=hashlib.sha256(config.prompt.encode("utf-8")).hexdigest(),
                    task_id=config.task_id,
                    suite_version=config.suite_version,
                    segment=config.segment,
                    output_type=config.output_type,
                    runner=config.runner_id,
                    tool_policy=config.tool_policy,
                    objective_metric=config.objective_metric,
                )
                report = evaluate_policy(evidence, config.policy_config)
                evidence_payload = asdict(evidence)
                decision_payload = report.to_dict()
                decision_markdown = decision_report_markdown(report)
                logger.event(
                    "policy_evaluated",
                    action=report.action.value,
                    reason_codes=[reason.value for reason in report.reason_codes],
                    paired_samples=report.paired_sample_count,
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
            if evidence_payload is not None:
                result.update(
                    {
                        "evidence": evidence_payload,
                        "decision": decision_payload,
                        "decision_markdown": decision_markdown,
                    }
                )
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
        run_context = build_run_context(logger.path, version, run_index)
        logger.event(
            "attempt_start",
            version=version,
            run_index=run_index,
            cwd=str(cwd),
            raw_stdout_log=str(run_context.raw_stdout_path) if run_context.raw_stdout_path else None,
            raw_stderr_log=str(run_context.raw_stderr_path) if run_context.raw_stderr_path else None,
        )
        logger.event(
            "codex_invocation_logs",
            level="debug",
            version=version,
            run_index=run_index,
            stdout_jsonl=str(run_context.raw_stdout_path) if run_context.raw_stdout_path else None,
            stderr=str(run_context.raw_stderr_path) if run_context.raw_stderr_path else None,
        )
        attempt = runner.run(cwd=cwd, prompt=prompt, context=run_context)
        attempt["run_index"] = run_index
        diff = capture_git_diff(cwd)
        attempt["git_diff"] = {
            "changed_files": diff["changed_files"],
            "name_status": diff["name_status"],
            "status_porcelain": diff["status_porcelain"],
            "stat": diff["stat"],
            "diff": diff["diff"],
        }
        if diff["error"]:
            logger.event(
                "attempt_git_diff_error",
                level="debug",
                version=version,
                run_index=run_index,
                cwd=str(cwd),
                error=diff["error"],
            )
        else:
            logger.event(
                "attempt_git_diff",
                level="debug",
                version=version,
                run_index=run_index,
                cwd=str(cwd),
                changed_files=diff["changed_files"],
                changed_file_count=len(diff["changed_files"]),
                name_status=diff["name_status"],
                status_porcelain=diff["status_porcelain"],
                stat=diff["stat"],
                diff=diff["diff"],
            )
        if capture_artifact:
            attempt["artifact"] = commit_attempt(cwd, version, run_index, diff)
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


def commit_attempt(cwd: Path, version: str, run_index: int, diff: dict[str, Any] | None = None) -> dict[str, Any]:
    diff = diff or capture_git_diff(cwd)
    changed_files = list(diff.get("status_porcelain", []))
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


def build_run_context(log_file: Path | None, version: str, run_index: int) -> RunContext:
    if not log_file:
        return RunContext(version=version, run_index=run_index)
    base = log_file.with_suffix("")
    return RunContext(
        version=version,
        run_index=run_index,
        raw_stdout_path=base.with_name(f"{base.name}.codex-{version}-run-{run_index}.stdout.jsonl"),
        raw_stderr_path=base.with_name(f"{base.name}.codex-{version}-run-{run_index}.stderr.log"),
    )


def capture_git_diff(cwd: Path) -> dict[str, Any]:
    status = run_git(cwd, "status", "--porcelain")
    intent_to_add = run_git(cwd, "add", "-N", ".")
    stat = run_git(cwd, "diff", "--stat", "--find-renames")
    name_status = run_git(cwd, "diff", "--name-status", "--find-renames")
    name_only = run_git(cwd, "diff", "--name-only", "--find-renames")
    diff = run_git(cwd, "diff", "--no-ext-diff", "--find-renames")

    errors = [
        item["stderr"]
        for item in (status, intent_to_add, stat, name_status, name_only, diff)
        if item["returncode"] != 0
    ]
    return {
        "changed_files": [line for line in name_only["stdout"].splitlines() if line],
        "name_status": [line for line in name_status["stdout"].splitlines() if line],
        "status_porcelain": [line for line in status["stdout"].splitlines() if line],
        "stat": stat["stdout"],
        "diff": diff["stdout"],
        "error": "\n".join(errors),
    }


def run_git(cwd: Path, *args: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr.strip(),
    }


def resolve_source_revisions(
    project: Path, candidate_commit: str, baseline_commit: str
) -> tuple[str, str]:
    repository_root = Path(
        git(project, "rev-parse", "--show-toplevel").strip()
    ).resolve()
    project_relative = project.resolve().relative_to(repository_root)
    agents_path = (project_relative / "AGENTS.md").as_posix()
    changed_paths = {
        path
        for path in git(
            project,
            "diff",
            "--name-only",
            baseline_commit,
            candidate_commit,
        ).splitlines()
        if path
    }
    if changed_paths.issubset({agents_path}):
        merge_base = git(
            project, "merge-base", baseline_commit, candidate_commit
        ).strip()
        shared_revision = f"{merge_base}:source-excluding-{agents_path}"
        return shared_revision, shared_revision
    return candidate_commit, baseline_commit
