from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SKILL_MD_PATH = Path(__file__).resolve().parent.parent.parent / ".claude" / "skills" / "agent-report" / "SKILL.md"
DEFAULT_MODEL = os.environ.get("CODEX_REPORT_MODEL", "gpt-5-codex")


def load_instructions() -> str:
    """Strip the YAML frontmatter off SKILL.md and return the reusable prompt body."""
    text = SKILL_MD_PATH.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, rest = text.partition("---\n")
        _, _, rest = rest.partition("---\n")
        return rest.strip()
    return text.strip()


def build_prompt(benchmark_data: str) -> str:
    """Combine the reusable report-skill prompt with whatever benchmark data was given."""
    instructions = load_instructions()
    return (
        f"{instructions}\n\n"
        "## Input\n\n"
        "Here is the benchmark data to work from. Its shape is whatever it is — "
        "structured, aggregated, or free-form text. Follow the instructions above "
        "and return only the human-readable report — no JSON.\n\n"
        f"{benchmark_data.strip()}\n"
    )


def load_input(path: Path) -> str:
    """Load benchmark data as-is. JSON/JSONL is pretty-printed for readability;
    anything else (plain text, markdown, free-form notes) is passed through untouched."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        return json.dumps(records, indent=2)
    if path.suffix == ".json":
        return json.dumps(json.loads(text), indent=2)
    return text


def run_codex(prompt: str, model: str) -> str:
    """Call the Codex/OpenAI API directly (no CLI subprocess) and return the report text."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment issue, not logic
        raise RuntimeError("The 'openai' package is required: pip install openai") from exc

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI()
    response = client.responses.create(model=model, input=prompt)
    text = getattr(response, "output_text", None)
    if not text:
        raise RuntimeError("Codex API returned no output_text")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentcd-report",
        description=(
            "Generate the final agent-comparison report from already-scored "
            "per-run benchmark records, using AGENT.md as the report prompt "
            "and calling the Codex API directly."
        ),
    )
    parser.add_argument("--input", required=True, help="Path to the benchmark data: JSON, JSONL, or free-form text/markdown.")
    parser.add_argument("--output", help="Path to write the report to. Defaults to stdout.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Codex model name. Default: {DEFAULT_MODEL} (or $CODEX_REPORT_MODEL).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        benchmark_data = load_input(Path(args.input))
        prompt = build_prompt(benchmark_data)
        report = run_codex(prompt, model=args.model)
    except Exception as exc:  # noqa: BLE001 - surface any failure as a clean CLI error
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
