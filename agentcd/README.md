# agentcd

`agentcd` benchmarks how two committed versions of `AGENTS.md` affect Codex runs.

## Example

```bash
python -m agentcd_bench \
  --project /path/to/repo \
  --commit-a abc123 \
  --commit-b def456 \
  --prompt-file examples/grafana-like-codebase/prompt.txt \
  --runs 3
```

If commits are omitted, the CLI uses:

- version A: current project `HEAD`
- version B: `main`

The default project is the repository's `hugoDocs` folder. Pass `--project` to override it.

## Output

The CLI prints compact JSON first, followed by a side-by-side comparison table unless `--json-only` is set. Compact JSON includes diff metadata but omits the full patch. Use `--verbose` to print the full per-attempt JSON payload, including full `git diff` patches, for downstream analysis or report generation.

The JSON includes:

- per-run LLM metrics
- per-run tool call metrics
- avg, p50, and p90 summaries for each version

Each run also writes JSONL trace logs. By default logs go to:

```text
logs/agents-bench-<timestamp>.jsonl
```

Override the path with:

```bash
--log-file /tmp/agents-bench.jsonl
```

The CLI appends the invocation timestamp to explicit log files, so that example writes `/tmp/agents-bench-<timestamp>.jsonl`. If `--log-file` points to a directory, the CLI writes `agents-bench-<timestamp>.jsonl` inside it.

Trace logs include CLI start/end, sanitized args, cwd, runner choice, prompt source, prompt length, prompt SHA-256, benchmark start/end, setup progress, worktree paths, version submit/start/end, attempt start/end, per-attempt raw Codex log paths, full `git diff`, changed files, diff name-status, porcelain status, diff stat, parsed attempt metrics, summary creation, status, duration, token totals, and tool-call count. Untracked files are included by marking them intent-to-add in the temporary worktree before diff capture. Raw inline prompt text is redacted. To watch progress while a run is active:

```bash
tail -f logs/agents-bench-<timestamp>.jsonl
```

Each Codex invocation also gets separate raw logs in the same directory:

```text
<main-log-stem>.codex-a-run-1.stdout.jsonl
<main-log-stem>.codex-a-run-1.stderr.log
<main-log-stem>.codex-b-run-1.stdout.jsonl
<main-log-stem>.codex-b-run-1.stderr.log
```

Tail an individual Codex run while it is active:

```bash
tail -f logs/<main-log-stem>.codex-a-run-1.stdout.jsonl
```

Version A and version B run concurrently after both worktrees are created. Repeated runs within the same version run sequentially.

The reported token counts are the totals emitted by the runner. For `--runner codex`, that means Codex CLI usage for the full fresh session context, not only the literal text passed through `--prompt` or `--prompt-file`.

## Architecture

The CLI is intentionally thin:

- `agentcd_bench.cli` handles flags and output.
- `agentcd_bench.service` owns benchmark orchestration and can later be called from FastAPI.
- `agentcd_bench.codex_client.Runner` is the execution boundary.
- `CodexExecRunner` currently shells out to `codex exec --ephemeral --sandbox workspace-write`.
- A future direct Codex API runner can replace `CodexExecRunner` without changing worktree orchestration or metrics aggregation.

## Validate The CLI

From this folder:

```bash
python -m unittest discover -s tests
```

Run a local smoke test without Codex credentials:

```bash
python -m agentcd_bench \
  --project /path/to/git/repo \
  --commit-a HEAD \
  --commit-b master \
  --prompt "Find and explain the main entrypoint." \
  --runs 1 \
  --runner mock
```

Run against the local Codex CLI:

```bash
python -m agentcd_bench \
  --project /path/to/git/repo \
  --commit-a abc123 \
  --commit-b def456 \
  --prompt-file examples/grafana-like-codebase/prompt.txt \
  --runs 1 \
  --runner codex
```

To commit each generated result temporarily and send each paired attempt to the Greptile FastAPI service, start the service separately and add:

```bash
python -m agentcd_bench \
  --project /path/to/repo \
  --commit-a candidate-sha \
  --commit-b baseline-sha \
  --prompt "Rename old_function to new_function and update all callers and tests." \
  --runs 1 \
  --runner codex \
  --base-branch main \
  --evaluator-url http://127.0.0.1:8000
```

AgentCD resets each evaluated attempt to its starting commit, captures its patch and changed files, creates an unpushed temporary commit and branch, calls `POST /evaluations` once for the candidate/baseline pair, includes the complete response under `evaluations`, and deletes the temporary branches after the response returns.

The `codex` runner shells out to `codex exec --json --ephemeral --sandbox workspace-write --cd <worktree>`, closes inherited stdin, parses JSONL events when available, and always records status and wall-clock duration.

Generate verbose machine-readable benchmark output for `agentcd-report`:

```bash
python -m agentcd_bench \
  --project /path/to/git/repo \
  --commit-a candidate-sha \
  --commit-b baseline-sha \
  --prompt-file examples/grafana-like-codebase/prompt.txt \
  --runs 3 \
  --runner codex \
  --json-only \
  --verbose > benchmark.json

agentcd-report --input benchmark.json --output report.md
```

## Offline Evaluation Policy

`agentcd_bench.evaluation` is the deterministic policy boundary that decides whether normalized offline evidence is eligible for shadow traffic. It performs no network, filesystem, Git, Greptile, database, or routing operations.

AgentCD calls the payload entrypoint after its deterministic checks and Greptile adapter have produced named baseline/candidate evidence:

```python
from agentcd_bench.evaluation import evaluate_policy_payload

decision = evaluate_policy_payload(evidence_payload, policy_config_payload)
result = decision.to_dict()
```

The contracts reject unknown schema or policy versions. Valid but incomplete evaluator data produces `hold`; configured critical findings or forbidden side effects produce `reject`. The offline-v1 policy can return `promote`, `hold`, `reject`, or `human_review`, but never changes traffic itself.

Canonical payloads are in `tests/fixtures/evaluation/healthy_evidence.json` and `tests/fixtures/evaluation/offline_policy.json`. The thresholds in that policy are demo fixtures, not calibrated production defaults.
