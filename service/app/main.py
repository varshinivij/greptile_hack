import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .evaluator import Evaluator
from .greptile import GreptileEvaluator
from .models import (
    EvaluationPairRequest,
    EvaluationPairResponse,
    EvaluationRequest,
    EvaluationResult,
)


def create_app(evaluator: Evaluator | None = None, settings: Settings | None = None) -> FastAPI:
    configured_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.evaluator = evaluator or GreptileEvaluator(
            binary=configured_settings.greptile_binary,
            timeout_seconds=configured_settings.greptile_timeout_seconds,
        )
        yield

    app = FastAPI(title="Greptile Evaluation Service", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/evaluations", response_model=EvaluationPairResponse)
    async def evaluations(payload: EvaluationPairRequest, request: Request) -> EvaluationPairResponse:
        repo = payload.repo or (
            str(configured_settings.default_repo) if configured_settings.default_repo else None
        )
        if repo is None:
            raise HTTPException(422, "repo is required when EVAL_DEFAULT_REPO is not configured")

        evaluator_instance: Evaluator = request.app.state.evaluator
        evaluation_a = EvaluationRequest(
            repo=repo,
            base_branch=payload.base_branch,
            branch=payload.branch_a,
            commit_id=payload.commit_a,
        )
        evaluation_b = EvaluationRequest(
            repo=repo,
            base_branch=payload.base_branch,
            branch=payload.branch_b,
            commit_id=payload.commit_b,
        )
        result_a, result_b = await asyncio.gather(
            _safe_evaluate(evaluator_instance, evaluation_a),
            _safe_evaluate(evaluator_instance, evaluation_b),
        )
        return EvaluationPairResponse(evaluations={"a": result_a, "b": result_b})

    return app


async def _safe_evaluate(evaluator: Evaluator, item: EvaluationRequest):
    """Keep an unexpected evaluator exception from affecting its peer review."""
    started = time.perf_counter()
    try:
        return await evaluator.evaluate(item)
    except Exception as exc:
        return EvaluationResult(
            branch=item.branch,
            commit_id=item.commit_id,
            status="failure",
            duration_ms=round((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )


app = create_app()
