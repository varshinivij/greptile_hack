from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .codex_client import Runner
from .git_worktrees import WorktreeManager
from .metrics import summarize_attempts


@dataclass(frozen=True)
class BenchmarkConfig:
    project: Path
    commit_a: str | None
    commit_b: str | None
    prompt: str
    runs: int = 1
    keep_worktrees: bool = False


def run_benchmark(config: BenchmarkConfig, runner: Runner) -> dict[str, Any]:
    with WorktreeManager(
        project=config.project,
        commit_a=config.commit_a,
        commit_b=config.commit_b,
        keep=config.keep_worktrees,
    ) as worktrees:
        attempts_a = run_attempts(runner, worktrees.path_a, config.prompt, config.runs)
        attempts_b = run_attempts(runner, worktrees.path_b, config.prompt, config.runs)
        return {
            "project": str(config.project),
            "run_count": config.runs,
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


def run_attempts(runner: Runner, cwd: Path, prompt: str, runs: int) -> list[dict[str, Any]]:
    attempts = []
    for run_index in range(1, runs + 1):
        attempt = runner.run(cwd=cwd, prompt=prompt)
        attempt["run_index"] = run_index
        attempts.append(attempt)
    return attempts
