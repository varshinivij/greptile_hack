from __future__ import annotations

from copy import deepcopy
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


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "project": result.get("project"),
        "run_count": result.get("run_count"),
        "log_file": result.get("log_file"),
        "execution": result.get("execution"),
        "runs": [],
    }
    for field in ("evidence", "decision", "decision_report"):
        if field in result:
            compact[field] = result[field]
    for run in result.get("runs", []):
        compact_attempts = []
        for attempt in run.get("attempts", []):
            compact_attempts.append(
                {
                    "run_index": attempt.get("run_index"),
                    "status": attempt.get("status"),
                    "returncode": attempt.get("returncode"),
                    "llm_metrics": attempt.get("llm_metrics"),
                    "tool_metrics": summarize_tool_metrics(attempt.get("tool_metrics", {})),
                    "git_diff": compact_git_diff(attempt.get("git_diff", {})),
                    "raw_logs": attempt.get("raw_logs"),
                    "error": attempt.get("error"),
                }
            )
        compact["runs"].append(
            {
                "version": run.get("version"),
                "commit": run.get("commit"),
                "worktree": run.get("worktree"),
                "attempts": compact_attempts,
                "summary": run.get("summary"),
            }
        )
    return compact


def verbose_result(result: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(result)


def compact_git_diff(git_diff: dict[str, Any]) -> dict[str, Any]:
    compact = deepcopy(git_diff)
    if "diff" in compact:
        compact["diff_truncated"] = True
        compact.pop("diff", None)
    return compact


def summarize_tool_metrics(tool_metrics: dict[str, Any]) -> dict[str, Any]:
    summary = deepcopy(tool_metrics)
    for tool_call in summary.get("tool_calls", []):
        commands = tool_call.get("commands")
        if isinstance(commands, list) and len(commands) > 5:
            tool_call["commands"] = commands[:5]
            tool_call["commands_truncated"] = len(commands) - 5
    return summary
