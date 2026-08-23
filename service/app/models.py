from typing import Any, Literal

from pydantic import BaseModel, Field


class EvaluationPairRequest(BaseModel):
    repo: str | None = None
    base_branch: str = "main"
    branch_a: str
    commit_a: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")
    branch_b: str
    commit_b: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")


class EvaluationRequest(BaseModel):
    repo: str
    base_branch: str
    branch: str
    commit_id: str


class EvaluationResult(BaseModel):
    branch: str
    commit_id: str
    status: Literal["success", "failure"]
    duration_ms: int = Field(ge=0)
    greptile_output: Any | None = None
    error: str | None = None
    stderr: str | None = None
    exit_code: int | None = None


class EvaluationPairResponse(BaseModel):
    evaluations: dict[Literal["a", "b"], EvaluationResult]
