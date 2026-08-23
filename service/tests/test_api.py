import asyncio
import time

from httpx import ASGITransport, AsyncClient

from app.evaluator import Evaluator
from app.config import Settings
from app.main import create_app
from app.models import EvaluationRequest, EvaluationResult


class FakeEvaluator(Evaluator):
    def __init__(self, failing_branch: str | None = None):
        self.failing_branch = failing_branch

    async def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        await asyncio.sleep(0.15)
        if request.branch == self.failing_branch:
            return EvaluationResult(
                branch=request.branch,
                commit_id=request.commit_id,
                status="failure",
                duration_ms=50,
                error="review failed",
                stderr="upstream error",
                exit_code=1,
            )
        return EvaluationResult(
            branch=request.branch,
            commit_id=request.commit_id,
            status="success",
            duration_ms=50,
            greptile_output={"complete": True, "nested": {"preserved": 1}},
        )


class ThrowingEvaluator(FakeEvaluator):
    async def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        if request.branch == "agent-a":
            raise RuntimeError("unexpected adapter error")
        return await super().evaluate(request)


async def post(app, payload):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/evaluations", json=payload)


PAYLOAD = {
    "repo": "/repo",
    "branch_a": "agent-a",
    "commit_a": "abc123",
    "branch_b": "agent-b",
    "commit_b": "def456",
}


async def test_runs_both_evaluations_concurrently_and_preserves_output():
    started = time.perf_counter()
    response = await post(create_app(FakeEvaluator()), PAYLOAD)
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.25
    body = response.json()["evaluations"]
    assert body["a"]["greptile_output"]["nested"]["preserved"] == 1
    assert body["b"]["commit_id"] == "def456"


async def test_one_failure_does_not_hide_the_other_result():
    response = await post(create_app(FakeEvaluator(failing_branch="agent-a")), PAYLOAD)

    assert response.status_code == 200
    body = response.json()["evaluations"]
    assert body["a"]["status"] == "failure"
    assert body["a"]["stderr"] == "upstream error"
    assert body["a"]["exit_code"] == 1
    assert body["b"]["status"] == "success"


async def test_unexpected_exception_does_not_cancel_peer():
    response = await post(create_app(ThrowingEvaluator()), PAYLOAD)
    body = response.json()["evaluations"]
    assert body["a"]["status"] == "failure"
    assert body["a"]["error"] == "RuntimeError: unexpected adapter error"
    assert body["b"]["status"] == "success"


async def test_requires_repo_when_no_default_is_configured():
    payload = {key: value for key, value in PAYLOAD.items() if key != "repo"}
    response = await post(create_app(FakeEvaluator(), Settings(default_repo=None)), payload)
    assert response.status_code == 422
    assert "EVAL_DEFAULT_REPO" in response.json()["detail"]
