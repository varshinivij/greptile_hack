# Greptile evaluation service

This FastAPI service reviews two exact Git commits with the Greptile CLI. Each commit is checked out in its own detached temporary Git worktree, and both `greptile review --branch <base> --json` processes run concurrently.

## Prerequisites

- Python 3.11+
- Git
- Greptile CLI 3.2.3+ installed and authenticated (`greptile login` or `GREPTILE_API_KEY`)
- A local clone with the requested commits and branch refs available, and an origin hosted on GitHub or GitLab

Install and run:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
uvicorn app.main:app --reload
```

Optionally set `EVAL_DEFAULT_REPO` so callers may omit `repo`. Other settings are shown in `.env.example`.
In this repository the built-in default is `../hugoDocs`; `EVAL_DEFAULT_REPO` can still override it.

Example request:

```powershell
$body = @{
  repo = "C:\path\to\repo"
  base_branch = "main"
  branch_a = "agent-a"
  commit_a = "abc123"
  branch_b = "agent-b"
  commit_b = "def456"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://localhost:8000/evaluations `
  -ContentType application/json -Body $body
```

The supplied commit must resolve locally and be an ancestor of its named local branch or `origin/<branch>`. This prevents a branch label from being paired accidentally with an unrelated commit. The original checkout is never switched or modified.

Run tests with `pytest`.
