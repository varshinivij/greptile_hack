# Agents Bench CLI Plan

## Goal

Build a simple CLI that compares how two committed versions of `AGENTS.md` affect Codex API runs.

Implementation lives under `agentcd`.

## Flow

```mermaid
flowchart TD
    CLI["agents-bench CLI<br/>--project repo<br/>--commit-a abc123<br/>--commit-b def456<br/>--prompt-file prompt.txt<br/>--runs N"]
    Validate["Validate repo<br/>Resolve commits<br/>Default A = current HEAD<br/>Default B = master"]
    Create["Same CLI process creates both temp worktrees"]

    CLI --> Validate --> Create

    Create --> WorktreeA["Worktree A<br/><tmp>/run-a<br/>git worktree add ... commit-a"]
    Create --> WorktreeB["Worktree B<br/><tmp>/run-b<br/>git worktree add ... commit-b"]

    WorktreeA --> CodexA["Run Codex N times<br/>cwd = run-a<br/>same prompt"]
    WorktreeB --> CodexB["Run Codex N times<br/>cwd = run-b<br/>same prompt"]

    Create -. "launch concurrently" .-> CodexA
    Create -. "launch concurrently" .-> CodexB

    CodexA --> MetricsA["Collect LLM metrics<br/>Collect tool metrics"]
    CodexB --> MetricsB["Collect LLM metrics<br/>Collect tool metrics"]

    MetricsA --> Output["Print JSON<br/>Print side-by-side table"]
    MetricsB --> Output

    Create --> Logs["Write JSONL trace logs"]
    CodexA --> Logs
    CodexB --> Logs

    Output --> Cleanup["Remove worktrees<br/>unless --keep-worktrees"]
```

## CLI

```bash
python -m agentcd_bench \
  --project /path/to/repo \
  --commit-a abc123 \
  --commit-b def456 \
  --prompt-file examples/grafana-like-codebase/prompt.txt \
  --runs 5
```

Defaults:

- `--commit-a`: current `HEAD`
- `--commit-b`: `master`
- `--runs`: `1`

## Modules

- `agentcd_bench.cli`: argument parsing, printing, exit codes
- `agentcd_bench.service`: benchmark orchestration
- `agentcd_bench.git_worktrees`: commit resolution and worktree lifecycle
- `agentcd_bench.codex_client`: runner interface, Codex CLI runner, and mock runner
- `agentcd_bench.metrics`: avg, p50, p90 summaries
- `agentcd_bench.output`: comparison table rendering

The service creates both worktrees, then launches version A and version B concurrently. Repeated runs inside a single version stay sequential for simpler per-version aggregation.

The CLI stays thin and calls `run_benchmark()` in the service layer. That same service boundary can later be exposed through FastAPI. The runner interface is intentionally narrow so `CodexExecRunner`, which shells out to `codex exec --ephemeral`, can later be replaced by a direct Codex API implementation without changing worktree orchestration, metrics aggregation, or output formatting.

Each version run must use fresh context. The current CLI runner uses `--ephemeral` and closes inherited stdin so it does not resume, persist, or append unrelated session input. A future direct Codex API runner should create an independent request per worktree with only the benchmark prompt plus the intended repo/worktree context.

## Metrics

LLM metrics:

- model
- input tokens
- output tokens
- total tokens
- reasoning tokens
- cached input tokens
- duration

Tool metrics:

- total tool call count
- per-tool count
- per-tool duration when available

For multiple runs, summaries include `avg`, `p50`, and `p90`.

## Trace Logs

Each invocation writes JSONL trace logs so long-running benchmarks can be inspected while they are active.

Default path:

```text
logs/agents-bench-<timestamp>.jsonl
```

The path can be overridden with `--log-file`.

Logged events:

- benchmark start/end
- resolved commits
- created worktree paths
- version start/end
- attempt start/end
- attempt status
- total tokens
- duration
- tool-call count

`agentcd/logs/` is ignored by git.

## Example Fixture

The repo includes:

```text
agentcd/
  examples/
    grafana-like-codebase/
      AGENTS.md
      prompt.txt
```

The mock `AGENTS.md` models instructions for a large Grafana-like codebase that can handle feature work and bugfixes across frontend, backend, APIs, tests, and docs.

## Test And Validate

Run unit tests:

```bash
python -m unittest discover -s tests
```

Run a CLI smoke test without Codex credentials against any git repo with commits:

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
