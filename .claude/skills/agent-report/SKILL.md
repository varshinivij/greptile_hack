---
name: agent-report
description: Read whatever agentcd benchmark data is given (per-run scores for agent A/B, aggregated metrics, free-form run explanations — shape varies) and write a short human-readable report that pulls out the important findings and makes a final recommendation. Use when the user wants "which agent wins" or a comparison writeup from benchmark output. Never emit JSON — human-readable report only.
---

# agentcd report

You are given benchmark data comparing two or more coding agents (or agent
versions) on the same prompts — attached below this prompt. The shape of
that input is **not fixed**: it might be raw per-run records with scores per
prompt/agent/run, might already be summarized/aggregated numbers, might
include free-form evaluator explanations instead of (or alongside) numeric
scores, or might mix all of that. Read what's actually there and work with
it — do not expect or demand a particular schema.

When generating a report from a fresh `agentcd` benchmark run, prefer
capturing verbose machine-readable benchmark output first:

```bash
python -m agentcd_bench \
  --project /path/to/git/repo \
  --commit-a candidate-sha \
  --commit-b baseline-sha \
  --prompt-file prompt.txt \
  --runs 3 \
  --runner codex \
  --json-only \
  --verbose > benchmark.json

agentcd-report --input benchmark.json --output report.md
```

Use verbose benchmark JSON because it preserves per-attempt metrics, raw
Codex log paths, full `git diff` patches, diff metadata, and tool-call
details that may be lost or truncated in compact CLI output.

**You make the recommendation.** Nothing upstream has decided a winner for
you. Weigh the evidence yourself: which agent actually did better on
correctness/task success, code quality, tests, and any Greptile or
evaluator score present, then factor in efficiency (tokens, duration, tool
calls) as secondary color, not the deciding factor. If explanations are
qualitative rather than numeric, reason over them the same way a person
would — read what actually happened in the runs, not just a headline score.

Output is **human-readable prose/markdown only. Never emit JSON.** No code
fences of JSON, no schema, no structured object — a report a person reads.

## What the report must do

1. **Pull out the important findings** — don't just restate every number.
   Say what actually distinguishes the agents: where one is clearly
   stronger, where they're roughly tied, and where the evidence is thin or
   missing.
2. **Give a final recommendation**, stated plainly as one of:
   - `Recommend <agent>` — with the size of the lead and what it's based on;
   - `No clear winner` — describe the actual trade-off (e.g. one is more
     correct, the other faster/cheaper), including where the "losing" agent
     is actually ahead;
   - `Not enough evidence` — if the input is too thin, too one-sided (e.g.
     only one agent has data), or too contradictory to responsibly call.
3. **Back the recommendation with specifics**, not vibes: cite the actual
   scores/metrics/quotes from the input that drove the call. If two agents
   are close, say how close and what would need to differ to flip the call.
4. **Flag data quality problems as you find them**: missing scores, only
   partial prompt coverage, small sample sizes, inconsistent scoring across
   agents, runs that failed/timed out. These affect how much to trust the
   recommendation — say so, don't bury it.

## Constraints

- Never invent a number, score, or outcome that isn't in the input. If
  something is missing, say it's missing — don't estimate it to fill a gap.
- Don't let token/duration/cost differences override a real quality gap —
  mention them, but the recommendation should hinge on correctness/quality
  unless the input shows quality is genuinely a wash.
- Keep it scannable: lead with the recommendation and the one or two facts
  that justify it, then the supporting detail. Don't bury the verdict at the
  bottom.
- If the input covers only one agent, or isn't a comparison at all, say so
  instead of forcing a recommendation.
