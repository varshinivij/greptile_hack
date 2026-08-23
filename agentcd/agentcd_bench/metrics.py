from __future__ import annotations

import math
from statistics import mean
from typing import Any


SUMMARY_FIELDS = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "duration_ms",
    "tool_call_count",
]


def summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    values: dict[str, list[float]] = {field: [] for field in SUMMARY_FIELDS}
    for attempt in attempts:
        llm = attempt.get("llm_metrics", {})
        tools = attempt.get("tool_metrics", {})
        for field in SUMMARY_FIELDS:
            source = tools if field == "tool_call_count" else llm
            value = source.get(field)
            if isinstance(value, int | float):
                values[field].append(float(value))

    return {
        field: {
            "avg": round(mean(field_values), 2),
            "p50": percentile(field_values, 50),
            "p90": percentile(field_values, 90),
        }
        for field, field_values in values.items()
        if field_values
    }


def percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil((percent / 100) * len(ordered)))
    return ordered[rank - 1]
