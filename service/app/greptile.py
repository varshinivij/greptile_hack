import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from .evaluator import Evaluator
from .models import EvaluationRequest, EvaluationResult


class CommandError(Exception):
    def __init__(self, message: str, stderr: str = "", exit_code: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.exit_code = exit_code


class GreptileEvaluator(Evaluator):
    def __init__(self, binary: str = "greptile", timeout_seconds: float = 600.0):
        self.binary = binary
        self.timeout_seconds = timeout_seconds

    async def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        started = time.perf_counter()
        try:
            repo, project_relative = await self._validate_request(request)
            output = await self._review_in_worktree(repo, project_relative, request)
            return EvaluationResult(
                branch=request.branch,
                commit_id=request.commit_id,
                status="success",
                duration_ms=self._elapsed_ms(started),
                greptile_output=output,
            )
        except CommandError as exc:
            return EvaluationResult(
                branch=request.branch,
                commit_id=request.commit_id,
                status="failure",
                duration_ms=self._elapsed_ms(started),
                error=str(exc),
                stderr=exc.stderr or None,
                exit_code=exc.exit_code,
            )
        except Exception as exc:
            return EvaluationResult(
                branch=request.branch,
                commit_id=request.commit_id,
                status="failure",
                duration_ms=self._elapsed_ms(started),
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _validate_request(self, request: EvaluationRequest) -> tuple[Path, Path]:
        requested_path = Path(request.repo).expanduser().resolve()
        if not requested_path.is_dir():
            raise CommandError(f"repository does not exist: {requested_path}")

        await self._git(requested_path, "rev-parse", "--is-inside-work-tree")
        root_text = await self._git(requested_path, "rev-parse", "--show-toplevel")
        repo = Path(root_text).resolve()
        project_relative = requested_path.relative_to(repo)
        if request.branch.startswith("-") or request.base_branch.startswith("-"):
            raise CommandError("branch names cannot start with '-'")
        await self._git(repo, "rev-parse", "--verify", f"{request.commit_id}^{{commit}}")
        branch_ref = await self._resolve_branch(repo, request.branch)
        await self._resolve_branch(repo, request.base_branch)
        await self._git(repo, "merge-base", "--is-ancestor", request.commit_id, branch_ref)
        return repo, project_relative

    async def _resolve_branch(self, repo: Path, branch: str) -> str:
        for candidate in (branch, f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
            try:
                await self._git(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}")
                return candidate
            except CommandError:
                pass
        raise CommandError(f"branch cannot be resolved: {branch}")

    async def _review_in_worktree(
        self,
        repo: Path,
        project_relative: Path,
        request: EvaluationRequest,
    ):
        worktree = Path(tempfile.mkdtemp(prefix="greptile-eval-"))
        # `git worktree add` owns creation of the target path.
        worktree.rmdir()
        added = False
        try:
            await self._git(repo, "worktree", "add", "--detach", str(worktree), request.commit_id)
            added = True
            stdout, stderr, code = await self._run(
                self.binary,
                "review",
                "--branch",
                request.base_branch,
                "--json",
                cwd=worktree / project_relative,
                timeout=self.timeout_seconds,
            )
            if code != 0:
                raise CommandError("Greptile review failed", stderr, code)
            try:
                return json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise CommandError(f"Greptile returned invalid JSON: {exc}", stderr, code) from exc
        finally:
            if added:
                try:
                    await self._git(repo, "worktree", "remove", "--force", str(worktree))
                except CommandError:
                    pass
            shutil.rmtree(worktree, ignore_errors=True)

    async def _git(self, repo: Path, *args: str) -> str:
        stdout, stderr, code = await self._run("git", "-C", str(repo), *args)
        if code != 0:
            detail = stderr.strip() or stdout.strip()
            raise CommandError(f"git {' '.join(args)} failed: {detail}", stderr, code)
        return stdout.strip()

    @staticmethod
    async def _run(*args: str, cwd: Path | None = None, timeout: float | None = None):
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CommandError(f"executable not found: {args[0]}") from exc
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError as exc:
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            raise CommandError(
                f"command timed out after {timeout} seconds",
                stderr_bytes.decode(errors="replace"),
                process.returncode,
            ) from exc
        return (
            stdout_bytes.decode(errors="replace"),
            stderr_bytes.decode(errors="replace"),
            process.returncode,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
