"""Deterministic presentation helpers for evaluation decisions."""

from __future__ import annotations

from .models import DecisionAction, DecisionReport, GateStatus, Scalar


ACTION_LABELS = {
    DecisionAction.PROMOTE: "✅ PROMOTE",
    DecisionAction.HOLD: "⏸️ HOLD",
    DecisionAction.REJECT: "❌ REJECT",
    DecisionAction.ROLLBACK: "↩️ ROLLBACK",
    DecisionAction.HUMAN_REVIEW: "👤 HUMAN REVIEW",
}

GATE_LABELS = {
    GateStatus.PASSED: "✅ passed",
    GateStatus.FAILED: "❌ failed",
    GateStatus.HELD: "⏸️ held",
    GateStatus.REVIEW: "👤 review",
    GateStatus.NOT_EVALUATED: "⏭️ not evaluated",
}


def decision_report_markdown(report: DecisionReport) -> str:
    """Render the complete decision contract as stable, human-readable Markdown."""
    next_stage = report.next_stage.value if report.next_stage else "—"
    reason_codes = ", ".join(f"`{reason.value}`" for reason in report.reason_codes)
    segments = ", ".join(
        f"`{name}`: {count}" for name, count in report.segment_counts
    ) or "—"

    lines = [
        f"# AgentCD Decision: {ACTION_LABELS[report.action]}",
        "",
        (
            f"**Candidate** `{_escape_inline(report.candidate_version)}` vs "
            f"**baseline** `{_escape_inline(report.baseline_version)}` · "
            f"policy `{_escape_inline(report.policy_id)}@{_escape_inline(report.policy_version)}`"
        ),
        "",
        f"> {_escape_text(report.summary)}",
        "",
        f"**Stage:** `{report.current_stage.value}` → `{next_stage}`  ",
        f"**Reason codes:** {reason_codes or '—'}  ",
        f"**Coverage:** {report.paired_sample_count} paired samples · {segments}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Summary | Reason codes |",
        "| --- | --- | --- | --- |",
    ]

    for gate in report.gate_results:
        gate_reasons = ", ".join(f"`{reason.value}`" for reason in gate.reason_codes)
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{gate.name.value}`",
                    GATE_LABELS[gate.status],
                    _escape_table(gate.summary),
                    gate_reasons or "—",
                )
            )
            + " |"
        )

    observations = [
        (gate.name.value, observation)
        for gate in report.gate_results
        for observation in gate.observations
    ]
    if observations:
        lines.extend(
            (
                "",
                "## Observations",
                "",
                "| Gate | Metric | Baseline | Candidate | Observed | Threshold |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            )
        )
        for gate_name, observation in observations:
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"`{gate_name}`",
                        f"`{_escape_inline(observation.metric)}`",
                        _format_scalar(observation.baseline),
                        _format_scalar(observation.candidate),
                        _format_scalar(observation.observed),
                        _format_scalar(observation.threshold),
                    )
                )
                + " |"
            )

    missing_evidence = report.missing_evidence
    if missing_evidence:
        lines.extend(("", "## Missing evidence", ""))
        lines.extend(f"- `{_escape_inline(item)}`" for item in missing_evidence)

    lines.extend(
        (
            "",
            "---",
            "",
            (
                f"Decision schema `{_escape_inline(report.schema_version)}` · "
                f"evidence schema `{_escape_inline(report.evidence_schema_version)}`"
            ),
        )
    )
    return "\n".join(lines) + "\n"


def _format_scalar(value: Scalar) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value).lower()
    return _escape_table(str(value))


def _escape_inline(value: str) -> str:
    return value.replace("`", "\\`").replace("\n", " ")


def _escape_text(value: str) -> str:
    return value.replace("\n", " ")


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")
