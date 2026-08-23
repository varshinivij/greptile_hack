from __future__ import annotations

from typing import Any


TABLE_FIELDS = ["total_tokens", "duration_ms", "tool_call_count"]


def comparison_table(result: dict[str, Any]) -> str:
    runs = {run["version"]: run for run in result.get("runs", [])}
    headers = ["Metric", "Commit A avg", "Commit A p50", "Commit A p90", "Commit B avg", "Commit B p50", "Commit B p90"]
    rows = [headers, ["---", "---:", "---:", "---:", "---:", "---:", "---:"]]
    for field in TABLE_FIELDS:
        summary_a = runs.get("a", {}).get("summary", {}).get(field, {})
        summary_b = runs.get("b", {}).get("summary", {}).get(field, {})
        rows.append(
            [
                field,
                format_value(summary_a.get("avg")),
                format_value(summary_a.get("p50")),
                format_value(summary_a.get("p90")),
                format_value(summary_b.get("avg")),
                format_value(summary_b.get("p50")),
                format_value(summary_b.get("p90")),
            ]
        )
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
