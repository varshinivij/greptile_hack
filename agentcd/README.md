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

The `codex` runner shells out to `codex exec --json --cd <worktree>`, parses JSONL events when available, and always records status and wall-clock duration.
