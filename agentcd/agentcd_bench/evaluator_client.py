from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationClient:
    base_url: str
    timeout_seconds: float = 700.0

    def evaluate_pair(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/evaluations"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                if not isinstance(parsed, dict):
                    raise ValueError("evaluation service returned a non-object JSON response")
                return parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return self._failure(started, f"evaluation service returned HTTP {exc.code}", body)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            return self._failure(started, f"evaluation service request failed: {exc}")

    @staticmethod
    def _failure(started: float, error: str, response_body: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "failure",
            "duration_ms": round((time.monotonic() - started) * 1000),
            "error": error,
        }
        if response_body:
            result["response_body"] = response_body
        return result
