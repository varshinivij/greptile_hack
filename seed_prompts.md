You are generating synthetic tasks for evaluating AI coding agents.

Below is a collection of seed coding tasks.

For each seed, generate 20 unique variations.

Rules:
- Each variation must be a realistic request a software engineer might give to a coding agent.
- Do not simply reword the seed.
- Change the technical context, constraints, implementation details, difficulty, or surrounding requirements.
- Include a mixture of easy, medium, hard, and agent-hard tasks.
- Tasks should require the agent to inspect an existing repository rather than being solvable from the prompt alone.
- Prefer tasks involving multiple files for harder examples.
- Do not provide solutions.
- Do not provide code.
- Do not duplicate tasks.
- Keep each task between 1 and 5 sentences.

Return JSONL with:

{"prompt":"...", "category":"...", "difficulty":"...", "language":"...", "framework":"...", "multi_file":true}

SEEDS:



BUG FIXES
Fix the null pointer error that occurs when a user has no profile picture.
The login endpoint returns a 500 error when an invalid email is provided. Find and fix the issue.
Fix the pagination bug where the API skips records between pages.
The application crashes when an empty configuration file is loaded. Handle this case correctly.
Fix the race condition that causes duplicate jobs to be created.
The frontend sometimes displays stale user data after an update. Fix the state synchronization issue.
Fix the database query that fails when a search string contains special characters.
The CLI exits successfully even when the underlying command fails. Fix the exit code handling.
Fix the API timeout that occurs when processing large requests.
The application incorrectly treats expired authentication tokens as valid. Fix the token validation logic.
Fix the file upload endpoint so that corrupted files are rejected properly.
The cache returns incorrect results after a user updates their account. Fix the cache invalidation logic.
Fix the bug where deleting a parent record leaves orphaned child records.
The background worker occasionally processes the same job twice. Identify and fix the issue.
Fix the timezone handling bug causing timestamps to display incorrectly for users in different regions.
Find why the notification system is not sending emails and fix the issue.
Investigate the failing tests in the repository and fix the underlying problems.
The application is leaking database connections under heavy load. Find the cause and fix it.
Fix the issue causing background jobs to stop processing after an exception.
Investigate why the application behaves differently in development and production and fix the underlying configuration issue.

FEATURES
Add pagination to the users API.
Add a search endpoint that allows users to search products by name and description.
Add support for filtering orders by status and date range.
Implement email verification for newly registered users.
Add password reset functionality to the authentication system.
Add rate limiting to the public API.
Add a command to the CLI that displays the current configuration.
Add support for exporting user data as CSV.
Add dark mode to the frontend application.
Add an endpoint for retrieving a user's activity history.
Add retry logic for failed external API requests.
Add support for uploading multiple files at once.
Add a health-check endpoint that reports the status of dependent services.
Add role-based access control to the admin endpoints.
Add automatic cleanup of expired sessions.
Add support for soft deletion of users.
Implement an API endpoint that returns aggregated usage statistics.
Add webhook support for order status changes.
Add structured logging to all API requests.
Add a new configuration option while preserving the existing default behavior.

REFACTORING
Refactor the authentication logic so it can be shared across multiple API endpoints.
Break the large UserService class into smaller components with clear responsibilities.
Remove duplicated validation logic across the API controllers.
Refactor the database access layer to use a repository pattern.
Replace the current callback-based implementation with async/await.
Refactor the configuration system so environment-specific settings are handled cleanly.
Simplify the error-handling logic across the API.
Refactor the frontend state management so related state is grouped together.
Remove unused dependencies and dead code from the project.
Refactor the HTTP client so authentication, retries, and logging are handled centrally.
Find duplicated business logic in the codebase and refactor it without changing behavior.
Find all places where the deprecated API is being used and migrate them to the replacement.

TESTING
Add unit tests for the authentication service.
Increase test coverage for the payment processing module.
Add integration tests for the user registration flow.
Add tests covering invalid API requests and expected error responses.
Add regression tests for the pagination bug.
Mock the external payment API in the existing test suite.
Add tests for concurrent job processing.
Add end-to-end tests for the login and logout flows.
Fix the flaky tests in the background worker test suite.
Add property-based tests for the input validation module.
Add tests for the most important untested functionality in the repository.
Investigate the failing test suite and fix the underlying problems.

PERFORMANCE
The users endpoint becomes slow with more than 100,000 records. Investigate and optimize it.
Reduce the number of database queries performed when loading an order and its items.
Optimize the image-processing pipeline to reduce memory usage.
The application startup time has increased significantly. Identify the bottleneck and improve it.
Add caching to the expensive product lookup operation.
Optimize the frontend component that rerenders whenever unrelated application state changes.
Reduce the memory usage of the CSV import process.
Optimize the API endpoint that aggregates statistics across millions of records.
Add batching to the background job processor.
Profile the application and fix the most significant performance bottleneck you find.

SECURITY
Prevent SQL injection in the search endpoint.
Add input validation to the file upload API.
Ensure users cannot access another user's private resources by changing an ID in the URL.
Fix the authentication middleware so expired tokens cannot be used.
Prevent sensitive environment variables from being logged.
Add protection against brute-force login attempts.
Validate uploaded filenames to prevent path traversal attacks.
Review the API for endpoints that are missing authorization checks and fix them.
Ensure passwords are never returned in API responses.
Add secure HTTP headers to the web application.

API AND BACKEND
Add a REST endpoint for creating and deleting comments.
Update the API to return consistent error responses.
Add request validation using the project's existing validation framework.
Add sorting support to the products endpoint.
Implement optimistic locking for concurrent updates.
Add database migrations for the new notification tables.
Add support for soft deletion of users.
Implement an API endpoint that returns aggregated usage statistics.
Add webhook support for order status changes.
Add structured logging to all API requests.
Add support for the new API response format while maintaining backwards compatibility.
Add support for a new third-party API while following the existing integration patterns in the repository.
Add a new API endpoint while following the conventions already used in the project.
Improve the application's handling of network failures without changing its public API.

FRONTEND
Add loading and error states to the user profile page.
Fix the form validation on the registration page.
Add client-side pagination to the results table.
Refactor the dashboard into reusable components.
Fix the mobile layout of the navigation menu.
Add a confirmation dialog before deleting an account.
Prevent duplicate form submissions while a request is pending.
Add filtering and sorting controls to the dashboard.
Fix the frontend so API errors are displayed to users instead of silently failing.
Add an accessible keyboard navigation flow to the modal component.
Add optimistic UI updates for user profile changes.
Improve the loading experience for a page that depends on several API requests.

DATABASE
Add indexes to improve the performance of the most frequently used queries.
Create a migration for adding a new field to the users table.
Add database constraints to prevent invalid records.
Optimize a query that joins several large tables.
Add support for database transactions around a multi-step operation.
Fix a migration that fails on existing production data.
Add soft-delete support to the database schema.
Find and fix an N+1 query problem.
Add a database seed script for local development.
Update the database schema while preserving existing data.

DEVOPS AND CI/CD
Add a GitHub Actions workflow that runs the test suite on every pull request.
Update the Dockerfile to reduce the final image size.
Add a Docker Compose configuration for local development.
Add environment-specific configuration for development, staging, and production.
Configure the application to gracefully shut down when receiving SIGTERM.
Add automated dependency vulnerability scanning to CI.
Add a deployment health check to the CI pipeline.
Fix the Docker build failing on ARM64 systems.
Add caching to the GitHub Actions dependency installation step.
Add automatic database migrations to the deployment process.
Add a CI job that checks formatting and linting.
Fix the CI pipeline so failed tests correctly cause the build to fail.
Add a release workflow that builds and packages the application.

CLI AND TOOLING
Add a CLI command for inspecting application configuration.
Add a CLI command for importing data from a CSV file.
Fix the CLI so errors return non-zero exit codes.
Add progress reporting to a long-running CLI operation.
Add support for configuration through environment variables.
Add shell autocompletion to the CLI.
Improve the CLI error messages for invalid arguments.
Add a dry-run option to a destructive CLI command.
Add logging to the CLI while keeping normal output clean.
Add tests for the CLI argument parsing logic.

MULTI-FILE AND AGENTIC TASKS
Find why the application is failing to start and fix the underlying issue.
Review the repository and identify the cause of the failing tests, then fix it.
Add support for a new API response format and update all affected consumers.
Update the project to the latest compatible version of its main framework and fix resulting issues.
Find duplicated functionality across the codebase and consolidate it.
Add a feature while following the architecture and conventions already established in the repository.
Find the source of a memory leak and fix it.
Investigate a performance regression and fix the underlying bottleneck.
Replace a deprecated library throughout the repository while preserving existing behavior.
Add a new configuration option and update the documentation and tests accordingly.
Implement a feature across the API, database, and frontend.
Fix a bug that requires changes to multiple modules while maintaining backwards compatibility.
Review the existing implementation and make the smallest set of changes necessary to resolve the issue.
Find an appropriate location for a new feature based on the existing project architecture and implement it.
Investigate an issue reported by a user and determine whether it is caused by the frontend, backend, or database before fixing it.

AMBIGUOUS / REALISTIC USER REQUESTS
The login flow seems broken. Can you take a look and fix it?
Users are reporting that the dashboard is really slow. Please investigate.
Something is wrong with the notification system. Figure out what's happening.
Can you clean up the authentication code?
The API has been acting weird when there are lots of requests. Take a look.
The tests started failing after the latest dependency update. Fix whatever broke.
Can you make the user search faster?
We're getting duplicate records occasionally. Find out why.
The application crashes sometimes when processing large files. Please fix it.
Can you update this project to use the newer API?
The CI build has been flaky lately. Investigate and fix it.
The frontend isn't showing errors correctly. Fix the user experience.
Can you improve the error handling throughout the application?
Some users are seeing data that belongs to other users. Investigate this immediately.
The application works locally but fails in production. Find and fix the issue.
Can you add this feature without breaking the existing behavior?
The code around payments is getting difficult to maintain. Clean it up.
Can you look through the repository and improve the test coverage where it matters?
Something changed recently and the API got slower. Find out what happened.
Can you make this code more reliable when external services are unavailable?