# AGENTS.md

You are working in a large observability platform similar in size and shape to Grafana. Treat the repository as a multi-service product with frontend packages, backend services, shared APIs, data-source integrations, dashboards, alerting, provisioning, tests, and documentation.

## Working Rules

- Read the relevant code paths before editing. Start from route handlers, API clients, feature flags, plugin registration, or package entrypoints as appropriate.
- Prefer existing conventions over new abstractions. Match local naming, error handling, logging, test fixtures, and file layout.
- Keep changes scoped to the requested feature or bugfix. Avoid broad refactors unless they are required to make the requested behavior correct.
- For frontend work, trace state from API client to store/query hook to component rendering. Update tests around user-visible behavior.
- For backend work, trace request validation, permissions, service logic, persistence, and API response shape. Update unit or integration tests near the changed behavior.
- For cross-cutting changes, check generated types, API contracts, migrations, feature flags, and documentation.
- When fixing a bug, add a regression test that fails without the fix.
- When adding a feature, include focused coverage for the new behavior and edge cases.
- Before finishing, summarize changed files, validation commands, and any risks or follow-up work.

## Validation Bias

Use the narrowest reliable validation first, then broaden when the change crosses package or service boundaries. Prefer existing package scripts and test helpers over one-off commands.

## Output Expectations

Return a concise implementation summary with:

- what changed
- why it changed
- tests or checks run
- known limitations
