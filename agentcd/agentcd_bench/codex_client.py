from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class Runner(Protocol):
    def run(self, cwd: Path, prompt: str) -> dict[str, Any]:
        """Run Codex in cwd and return one attempt result."""


@dataclass(frozen=True)
class CodexExecRunner:
    command: str = "codex"
    model: str | None = None

    def run(self, cwd: Path, prompt: str) -> dict[str, Any]:
        cmd = [self.command, "exec", "--json", "--cd", str(cwd)]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.append(prompt)

        start = time.monotonic()
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
        duration_ms = round((time.monotonic() - start) * 1000)
        parsed = parse_codex_jsonl(proc.stdout)

        llm_metrics = parsed["llm_metrics"]
        llm_metrics["duration_ms"] = duration_ms
        if self.model and not llm_metrics.get("model"):
            llm_metrics["model"] = self.model

        result: dict[str, Any] = {
            "status": "success" if proc.returncode == 0 else "error",
            "llm_metrics": llm_metrics,
            "tool_metrics": parsed["tool_metrics"],
            "returncode": proc.returncode,
        }
        if proc.returncode != 0:
            result["error"] = proc.stderr.strip() or "codex exec failed"
        return result


@dataclass(frozen=True)
class MockCodexRunner:
    model: str | None = None

    def run(self, cwd: Path, prompt: str) -> dict[str, Any]:
        agents_path = cwd / "AGENTS.md"
        agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        input_tokens = max(1, (len(prompt) + len(agents_text)) // 4)
        output_tokens = max(1, len(prompt) // 8)
        tool_count = 1 + (len(agents_text) % 4)
        duration_ms = 100 + (input_tokens % 50)
        return {
            "status": "success",
            "llm_metrics": {
                "model": self.model or "mock-codex",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "reasoning_tokens": output_tokens // 2,
                "cached_input_tokens": input_tokens // 3,
                "duration_ms": duration_ms,
            },
            "tool_metrics": {
                "tool_call_count": tool_count,
                "tool_calls": [
                    {
                        "name": "mock_read",
                        "count": tool_count,
                        "duration_ms": duration_ms // 3,
                    }
                ],
            },
            "returncode": 0,
        }


def parse_codex_jsonl(stdout: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)

    llm_metrics: dict[str, Any] = {}
    tool_calls: dict[str, dict[str, Any]] = {}

    for event in events:
        usage = find_usage(event)
        if usage:
            merge_usage(llm_metrics, usage)

        tool_name = find_tool_name(event)
        if tool_name:
            entry = tool_calls.setdefault(tool_name, {"name": tool_name, "count": 0, "duration_ms": 0})
            entry["count"] += 1
            entry["duration_ms"] += find_duration_ms(event)

    input_tokens = llm_metrics.get("input_tokens", 0)
    output_tokens = llm_metrics.get("output_tokens", 0)
    total_tokens = llm_metrics.get("total_tokens") or input_tokens + output_tokens

    return {
        "llm_metrics": {
            "model": llm_metrics.get("model"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": llm_metrics.get("reasoning_tokens", 0),
            "cached_input_tokens": llm_metrics.get("cached_input_tokens", 0),
        },
        "tool_metrics": {
            "tool_call_count": sum(call["count"] for call in tool_calls.values()),
            "tool_calls": sorted(tool_calls.values(), key=lambda item: item["name"]),
        },
    }


def find_usage(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("usage"), dict):
            return value["usage"]
        for child in value.values():
            found = find_usage(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_usage(child)
            if found:
                return found
    return None


def merge_usage(target: dict[str, Any], usage: dict[str, Any]) -> None:
    aliases = {
        "input_tokens": ["input_tokens", "prompt_tokens"],
        "output_tokens": ["output_tokens", "completion_tokens"],
        "total_tokens": ["total_tokens"],
        "reasoning_tokens": ["reasoning_tokens"],
        "cached_input_tokens": ["cached_input_tokens", "cached_tokens"],
    }
    if usage.get("model"):
        target["model"] = usage["model"]
    for canonical, names in aliases.items():
        for name in names:
            if isinstance(usage.get(name), int):
                target[canonical] = usage[name]

    details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        target["reasoning_tokens"] = details["reasoning_tokens"]

    input_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    if isinstance(input_details, dict) and isinstance(input_details.get("cached_tokens"), int):
        target["cached_input_tokens"] = input_details["cached_tokens"]


def find_tool_name(event: dict[str, Any]) -> str | None:
    candidates = [
        event.get("tool_name"),
        event.get("name") if "tool" in str(event.get("type", "")).lower() else None,
    ]
    item = event.get("item")
    if isinstance(item, dict):
        candidates.extend([item.get("tool_name"), item.get("name")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def find_duration_ms(event: dict[str, Any]) -> int:
    for key in ("duration_ms", "elapsed_ms"):
        value = event.get(key)
        if isinstance(value, int):
            return value
    return 0
