from abc import ABC, abstractmethod

from .models import EvaluationRequest, EvaluationResult


class Evaluator(ABC):
    @abstractmethod
    async def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """Evaluate one exact commit against its base branch."""
