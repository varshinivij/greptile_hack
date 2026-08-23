"""CLI for replaying normalized evidence through the deterministic policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_policy_payload
from .evaluation.output import decision_report_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentcd-evaluate",
        description="Evaluate normalized AgentCD evidence and render the decision.",
    )
    parser.add_argument("--evidence", required=True, help="Normalized evidence JSON file.")
    parser.add_argument("--policy", required=True, help="Policy configuration JSON file.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Decision output format. Default: markdown.",
    )
    parser.add_argument(
        "--output",
        help="Write the report to this file instead of standard output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    report = evaluate_policy_payload(evidence, policy)

    if args.format == "json":
        rendered = json.dumps(report.to_dict(), indent=2) + "\n"
    else:
        rendered = decision_report_markdown(report)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
