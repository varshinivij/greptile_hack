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
- version B: `master`

## Output

The CLI prints JSON first, followed by a side-by-side comparison table unless `--json-only` is set.

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

Trace logs include CLI start/end, sanitized args, cwd, runner choice, prompt source, prompt length, prompt SHA-256, benchmark start/end, setup progress, worktree paths, version submit/start/end, attempt start/end, parsed attempt metrics, summary creation, status, duration, token totals, and tool-call count. Raw inline prompt text is redacted. To watch progress while a run is active:

```bash
tail -f logs/agents-bench-<timestamp>.jsonl
```

Version A and version B run concurrently after both worktrees are created. Repeated runs within the same version run sequentially.

The reported token counts are the totals emitted by the runner. For `--runner codex`, that means Codex CLI usage for the full fresh session context, not only the literal text passed through `--prompt` or `--prompt-file`.

## Architecture

The CLI is intentionally thin:

- `agentcd_bench.cli` handles flags and output.
- `agentcd_bench.service` owns benchmark orchestration and can later be called from FastAPI.
- `agentcd_bench.codex_client.Runner` is the execution boundary.
- `CodexExecRunner` currently shells out to `codex exec --ephemeral`.
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

The `codex` runner shells out to `codex exec --json --ephemeral --cd <worktree>`, closes inherited stdin, parses JSONL events when available, and always records status and wall-clock duration.
