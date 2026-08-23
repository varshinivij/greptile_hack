# Coding Agent Evaluation Contract

## Purpose

`agentcd` compares coding agents (or versions of an agent's `AGENTS.md`) on the
same repository tasks. The benchmark must produce more than token and latency
telemetry: it must evaluate the quality of each answer or code change and issue
a clear final recommendation.

The unit of evaluation is one **prompt × agent version × run**. A benchmark
contains one or more prompts, two or more agent versions, and repeated runs to
reduce variance.

## Fair-run rules

- Give every agent version the identical prompt, repository commit, environment,
  permissions, timeout, model configuration, and run count.
- Use separate temporary git worktrees so that changes from one run cannot leak
  into another.
- Preserve each run's raw agent output, structured events, patch/diff, command
  results, and evaluator input. Do not score a run only from its final message.
- Record failures explicitly. A timeout, invalid output, broken workspace, or
  evaluator failure is a scored outcome, not missing data.
- Keep the quality evaluator separate from the candidate agent. It must receive
  the prompt, relevant repository context, expected checks, agent output, diff,
  and test/tool results, but not the candidate's identity or version label.

## Required per-run record

Each attempt must include the existing LLM and tool metrics plus the fields
below. Use stable machine-readable keys so JSON can be consumed by a UI or
future API.

```json
{
  "prompt_id": "auth-token-refresh",
  "agent_id": "version-a",
  "run_number": 1,
  "status": "completed",
  "llm_metrics": {
    "model": "…",
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "reasoning_tokens": 0,
    "cached_input_tokens": 0,
    "duration_ms": 0
  },
  "tool_metrics": {
    "tool_call_count": 0,
    "per_tool_count": {},
    "per_tool_duration_ms": {}
  },
  "quality": {
    "task_success_score": 0,
    "greptile_score": 0,
    "code_quality_score": 0,
    "test_score": 0,
    "final_score": 0,
    "evaluator_summary": "…",
    "evaluator_evidence": []
  },
  "artifacts": {
    "final_output": "…",
    "diff_path": "…",
    "test_results_path": "…",
    "event_log_path": "…"
  }
}
```

Scores are numeric on a 0–100 scale; `null` means the metric was unavailable,
never zero. Report why it was unavailable.

## Quality scoring

Score each completed run using these weighted dimensions:

| Dimension | Weight | What it measures |
| --- | ---: | --- |
| Task success | 40% | Does the implementation or answer satisfy the prompt and acceptance criteria? |
| Greptile score | 30% | Greptile's assessment of repository-aware correctness, relevance, and code understanding. |
| Code quality | 20% | Correct scope, maintainability, safety, style, and avoidance of regressions. |
| Test score | 10% | Relevant tests pass; the agent adds or updates appropriate tests when the task calls for it. |

`final_score` is the weighted sum of available dimensions, normalized by the
sum of their available weights. Do not silently treat an unavailable quality
dimension as 0. If Greptile is required for a benchmark and cannot run, mark
the benchmark `incomplete` and withhold a winner unless the user explicitly
opts into a fallback evaluation.

For failed or timed-out runs, set `final_score` to `0`, retain all available
evidence and efficiency metrics, and state the failure reason. Never invent a
Greptile result.

## Prompt-level results

For every prompt, aggregate repeated runs for each agent and report:

- final score: average, p50, p90, standard deviation, and completed-run count;
- each quality component, including the Greptile score;
- LLM metrics: tokens by category and duration;
- tool metrics: total calls, calls by tool, and duration by tool;
- reliability: completion, timeout, test-pass, and evaluator-availability rates;
- qualitative evidence: concise evaluator rationale and links/paths to the
  highest- and lowest-scoring run artifacts.

Rank agents for a prompt by average final score. Break ties by, in order:

1. higher task-success average;
2. higher Greptile-score average;
3. higher completion rate;
4. lower p50 duration;
5. lower average total tokens.

## Overall decision

Weight prompts equally by default, unless the benchmark configuration supplies
explicit prompt weights that total 1.0. The overall agent score is the weighted
mean of its prompt-level average final scores. Efficiency metrics inform the
recommendation but must not replace quality.

Recommend an agent only when all of the following are true:

- it has a complete evaluation for every required prompt;
- it has no materially worse reliability rate (more than 5 percentage points);
- it leads overall by at least 3 score points, or the confidence interval /
  repeated-run evidence makes the lead credible.

Otherwise report **No clear winner** and describe the trade-off—for example,
one agent is more correct while the other is faster or cheaper. Flag prompt
categories where the losing agent is stronger; do not hide disagreement behind
an aggregate score.

## Final report format

The CLI must emit full JSON and a human-readable report. The report should be
short enough to scan and include:

1. benchmark metadata: repository commit, agent versions, model, prompts, run
   count, evaluator/Greptile version, and timestamp;
2. per-prompt side-by-side scorecard with final score, all quality components,
   completion rate, token total, duration, and tool calls;
3. overall scorecard and reliability summary;
4. recommendation: `Recommend <agent>`, `No clear winner`, or
   `Evaluation incomplete`;
5. the concrete reasons and artifact references supporting that decision;
6. caveats such as small sample size, unavailable metrics, flaky tests, or
   uneven prompt coverage.

The recommendation must name the winner, quantify the quality difference, and
call out meaningful efficiency costs. Example: “Recommend version A: +7.4
overall quality points, equal completion rate, 18% more tokens, and 11% lower
p50 duration.”

## Implementation guidance

- Extend `agentcd_bench.metrics` with quality and reliability aggregation; keep
  raw attempts intact.
- Extend `agentcd_bench.output` to render prompt-level and overall scorecards,
  not only token/duration/tool-call rows.
- Add an evaluator interface so Greptile can be implemented as a provider and
  replaced by a deterministic mock in tests.
- Add fixtures and tests covering a Greptile success, unavailable Greptile,
  timeout, weighted-score normalization, tie-breaking, and no-clear-winner
  recommendation.
- Version the scoring rubric in every output so historical results remain
  interpretable after the rubric changes.
