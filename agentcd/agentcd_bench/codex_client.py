from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RunContext:
    version: str
    run_index: int
    raw_stdout_path: Path | None = None
    raw_stderr_path: Path | None = None


class Runner(Protocol):
    def run(self, cwd: Path, prompt: str, context: RunContext | None = None) -> dict[str, Any]:
        """Run Codex in cwd and return one attempt result."""


@dataclass(frozen=True)
class CodexExecRunner:
    command: str = "codex"
    model: str | None = None

    def run(self, cwd: Path, prompt: str, context: RunContext | None = None) -> dict[str, Any]:
        cmd = [
            self.command,
            "exec",
            "--json",
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(cwd),
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.append(prompt)

        start = time.monotonic()
        proc, stdout, stderr = run_process_with_optional_logs(cmd, cwd, context)
        duration_ms = round((time.monotonic() - start) * 1000)
        parsed = parse_codex_jsonl(stdout)

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
        if context:
            result["raw_logs"] = {
                "stdout_jsonl": str(context.raw_stdout_path) if context.raw_stdout_path else None,
                "stderr": str(context.raw_stderr_path) if context.raw_stderr_path else None,
            }
        if proc.returncode != 0:
            result["error"] = stderr.strip() or "codex exec failed"
        return result


@dataclass(frozen=True)
class MockCodexRunner:
    model: str | None = None

    def run(self, cwd: Path, prompt: str, context: RunContext | None = None) -> dict[str, Any]:
        if context and context.raw_stdout_path:
            context.raw_stdout_path.parent.mkdir(parents=True, exist_ok=True)
            context.raw_stdout_path.write_text(
                json.dumps(
                    {
                        "type": "mock.run",
                        "version": context.version,
                        "run_index": context.run_index,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        if context and context.raw_stderr_path:
            context.raw_stderr_path.parent.mkdir(parents=True, exist_ok=True)
            context.raw_stderr_path.write_text("", encoding="utf-8")
        agents_path = cwd / "AGENTS.md"
        agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        input_tokens = max(1, (len(prompt) + len(agents_text)) // 4)
        output_tokens = max(1, len(prompt) // 8)
        tool_count = 1 + (len(agents_text) % 4)
        duration_ms = 100 + (input_tokens % 50)
        result: dict[str, Any] = {
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
        if context:
            result["raw_logs"] = {
                "stdout_jsonl": str(context.raw_stdout_path) if context.raw_stdout_path else None,
                "stderr": str(context.raw_stderr_path) if context.raw_stderr_path else None,
            }
        return result


def run_process_with_optional_logs(
    cmd: list[str],
    cwd: Path,
    context: RunContext | None,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    if not context or not context.raw_stdout_path or not context.raw_stderr_path:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )
        return proc, proc.stdout, proc.stderr

    context.raw_stdout_path.parent.mkdir(parents=True, exist_ok=True)
    context.raw_stderr_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_thread = threading.Thread(
        target=stream_to_file,
        args=(proc.stdout, context.raw_stdout_path, stdout_chunks),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stream_to_file,
        args=(proc.stderr, context.raw_stderr_path, stderr_chunks),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    returncode = proc.wait()
    stdout_thread.join()
    stderr_thread.join()

    completed = subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )
    return completed, completed.stdout, completed.stderr


def stream_to_file(stream: Any, path: Path, chunks: list[str]) -> None:
    if stream is None:
        return
    with path.open("w", encoding="utf-8") as file:
        for line in stream:
            chunks.append(line)
            file.write(line)
            file.flush()


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
    active_tools: dict[str, dict[str, Any]] = {}

    for event in events:
        usage = find_usage(event)
        if usage:
            merge_usage(llm_metrics, usage)

        update_tool_metrics(event, tool_calls, active_tools)

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
            "failed_tool_call_count": sum(call.get("failed_count", 0) for call in tool_calls.values()),
            "tool_calls": sorted(tool_calls.values(), key=lambda item: item["name"]),
        },
    }


def update_tool_metrics(
    event: dict[str, Any],
    tool_calls: dict[str, dict[str, Any]],
    active_tools: dict[str, dict[str, Any]],
) -> None:
    event_type = str(event.get("type", ""))
    item = event.get("item")

    if isinstance(item, dict):
        item_id = str(item.get("id") or "")
        tool_name = tool_name_from_item(item)
        if tool_name and event_type == "item.started":
            entry = tool_entry(tool_calls, tool_name)
            entry["count"] += 1
            entry["started_count"] += 1
            append_sample(entry, "commands", item.get("command"))
            if item_id:
                active_tools[item_id] = {
                    "name": tool_name,
                    "started_at": event_timestamp(event),
                }
            return

        if tool_name and event_type == "item.completed":
            entry = tool_entry(tool_calls, tool_name)
            if item_id and item_id not in active_tools:
                entry["count"] += 1
            entry["completed_count"] += 1
            append_sample(entry, "commands", item.get("command"))
            status = item.get("status")
            exit_code = item.get("exit_code")
            if status not in (None, "completed", "success") or (isinstance(exit_code, int) and exit_code != 0):
                entry["failed_count"] += 1
            output = item.get("aggregated_output")
            if isinstance(output, str):
                entry["output_chars"] += len(output)
            started = active_tools.pop(item_id, None) if item_id else None
            duration_ms = duration_from_event_pair(started, event)
            entry["duration_ms"] += duration_ms if duration_ms is not None else find_duration_ms(event)
            return

    tool_name = find_generic_tool_name(event)
    if tool_name:
        entry = tool_entry(tool_calls, tool_name)
        entry["count"] += 1
        entry["duration_ms"] += find_duration_ms(event)


def tool_entry(tool_calls: dict[str, dict[str, Any]], tool_name: str) -> dict[str, Any]:
    return tool_calls.setdefault(
        tool_name,
        {
            "name": tool_name,
            "count": 0,
            "started_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "duration_ms": 0,
            "output_chars": 0,
            "commands": [],
        },
    )


def tool_name_from_item(item: dict[str, Any]) -> str | None:
    item_type = item.get("type")
    if item_type == "command_execution":
        return "command_execution"
    if isinstance(item_type, str) and item_type.endswith("_call"):
        return item_type
    if isinstance(item.get("tool_name"), str):
        return item["tool_name"]
    return None


def append_sample(entry: dict[str, Any], key: str, value: Any, limit: int = 20) -> None:
    if not isinstance(value, str) or not value:
        return
    samples = entry.setdefault(key, [])
    if value not in samples and len(samples) < limit:
        samples.append(value)


def event_timestamp(event: dict[str, Any]) -> float | None:
    for key in ("ts", "timestamp"):
        value = event.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def duration_from_event_pair(started: dict[str, Any] | None, completed_event: dict[str, Any]) -> int | None:
    if not started:
        return None
    started_at = started.get("started_at")
    completed_at = event_timestamp(completed_event)
    if isinstance(started_at, int | float) and isinstance(completed_at, int | float) and completed_at >= started_at:
        return round((completed_at - started_at) * 1000)
    return None


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


def find_generic_tool_name(event: dict[str, Any]) -> str | None:
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
