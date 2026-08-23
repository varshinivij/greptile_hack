from __future__ import annotations

import subprocess
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorktreePair:
    commit_a: str
    commit_b: str
    path_a: Path
    path_b: Path
    root_a: Path
    root_b: Path


class WorktreeManager(AbstractContextManager[WorktreePair]):
    def __init__(self, project: Path, commit_a: str | None, commit_b: str | None, keep: bool = False):
        self.project = project
        self.requested_commit_a = commit_a
        self.requested_commit_b = commit_b
        self.keep = keep
        self.tempdir: tempfile.TemporaryDirectory[str] | None = None
        self.pair: WorktreePair | None = None

    def __enter__(self) -> WorktreePair:
        ensure_git_repo(self.project)
        repository_root = Path(git(self.project, "rev-parse", "--show-toplevel").strip()).resolve()
        project_relative = self.project.resolve().relative_to(repository_root)
        commit_a = resolve_commit(self.project, self.requested_commit_a or "HEAD")
        commit_b = resolve_commit(self.project, self.requested_commit_b or "main")
        self.tempdir = tempfile.TemporaryDirectory(prefix="agents-bench-")
        base = Path(self.tempdir.name)
        root_a = base / "run-a"
        root_b = base / "run-b"
        git(repository_root, "worktree", "add", "--detach", str(root_a), commit_a)
        git(repository_root, "worktree", "add", "--detach", str(root_b), commit_b)
        self.pair = WorktreePair(
            commit_a=commit_a,
            commit_b=commit_b,
            path_a=root_a / project_relative,
            path_b=root_b / project_relative,
            root_a=root_a,
            root_b=root_b,
        )
        return self.pair

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.keep:
            return False
        if self.pair:
            for path in (self.pair.root_a, self.pair.root_b):
                subprocess.run(
                    ["git", "-C", str(self.project), "worktree", "remove", "--force", str(path)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
        if self.tempdir:
            self.tempdir.cleanup()
        return False


def ensure_git_repo(project: Path) -> None:
    if not project.exists():
        raise ValueError(f"project does not exist: {project}")
    proc = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        raise ValueError(f"project is not a git repository: {project}")


def resolve_commit(project: Path, ref: str) -> str:
    return git(project, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def git(project: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(project), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout
