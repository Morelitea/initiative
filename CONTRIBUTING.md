# Contributing to Initiative

Thanks for your interest in contributing! This guide covers what you need to know as a developer working on the codebase.

## Getting Set Up

### One-Click Dev Environment (Recommended)

The project includes a VS Code task configuration that starts everything with a single command:

1. **Prerequisites**: Docker, Python 3.10+ venv at `backend/.venv/`, Node.js 18+ with pnpm, PostgreSQL client tools (`pg_isready`)
2. **Configure**: Copy `backend/.env.example` to `backend/.env` and set `DATABASE_URL` / `SECRET_KEY`
3. **Launch**: Open the VS Code Command Palette (`Ctrl+Shift+P`) and run **Tasks: Run Task** → **`dev:setup`**

This will:
- Start PostgreSQL via Docker
- Run migrations and create a dev superuser (`admin@example.com` / `changeme`)
- Seed TTRPG-themed test data (campaigns, quests, NPCs, documents, tags)
- Start the backend (uvicorn) and frontend (Vite) dev servers
- Open the app in your browser

When you're done, run **`dev:cleanup`** from the task palette to remove all seeded test data. Stopping the debug session (if launched via F5) also triggers cleanup automatically.

**What gets seeded:**
- 2 campaign initiatives (Curse of Strahd, Lost Mine of Phandelver) + the default initiative
- 3 projects with 12 tasks across all priorities and statuses
- Subtasks, assignees, documents, tags, and comments
- All data is clearly TTRPG-themed so it's never confused with real data

The seeder saves created IDs to `.vscode/.dev_seed_ids.json` (gitignored) and uses them for clean teardown. See `scripts/seed_dev_data.py` for details.

### Manual Setup

Alternatively, follow the [Manual Development Setup](./README.md#manual-development-setup) in the README to start each service by hand. The [Key Environment Variables](./README.md#key-environment-variables) section covers configuration.

## Running Tests

```bash
# All backend tests
cd backend && pytest

# All frontend tests
cd frontend && pnpm test:run

# Only tests related to files you've changed (vs main)
cd backend && ./scripts/test-changed.sh
cd frontend && ./scripts/test-changed.sh

# Only tests for staged files
cd backend && ./scripts/test-changed.sh --staged
cd frontend && ./scripts/test-changed.sh --staged
```

## Code Style

- **Python**: 4-space indent, full type hints, `snake_case` functions, `PascalCase` models/schemas. Lint with `ruff check app`.
- **TypeScript/React**: `PascalCase` components, `useThing` hooks. Lint with `pnpm lint`.

Both linters must pass before merging.

## Project Layout

- `backend/app/api/` — FastAPI routers
- `backend/app/models/` — SQLModel domain models
- `backend/app/schemas/` — Request/response payloads
- `backend/app/services/` — Business logic
- `frontend/src/pages/` — Route-level React components
- `frontend/src/features/` — Feature-specific components and logic
- `frontend/src/hooks/` — Shared React hooks
- `frontend/src/api/` — API client and query hooks

Tests are co-located next to source files (`_test.py` for backend, `.test.ts` for frontend). Shared test factories live in `backend/app/testing/` and `frontend/src/__tests__/factories/`.

## Generated API Types

Frontend TypeScript types and React Query hooks are auto-generated from the backend's OpenAPI spec using [Orval](https://orval.dev). The generated files live in `frontend/src/api/generated/` and are committed to the repo.

**When you change backend schemas** (`backend/app/schemas/`), you must regenerate the frontend types:

```bash
# With the backend running locally:
cd frontend && pnpm generate:api

# Or without a running backend (export spec directly):
cd backend && python scripts/export_openapi.py ../frontend/openapi.json
cd frontend && pnpm orval
```

Commit the updated generated files alongside your schema changes. CI will fail if generated types are out of date.

**Important:** Do not hand-edit files in `frontend/src/api/generated/` — they will be overwritten on the next generation run.

## Submitting Changes

1. Fork the repo and create a branch from **`dev`**
2. Make your changes
3. Ensure tests and linters pass
4. Keep commits focused — separate backend, frontend, and infra changes when practical
5. Open a pull request **targeting `dev`** describing what changed and why
6. Include screenshots or GIFs for UI changes

**Important:** Do not open PRs against `main`. The `main` branch is restricted to project maintainers (@jordandrako, @LeeJMorel) who promote changes from `dev` using the release tooling below. PRs targeting `main` from non-maintainers will be closed.

## Releases (Maintainers)

Only project maintainers (@jordandrako, @LeeJMorel) have admin access to `main`. All changes reach `main` through the promotion script — never by direct push or PR.

### Branching Model

| Branch | Purpose |
|--------|---------|
| `main` | Production — admin-only, every commit is deployable |
| `dev` | Integration — all feature work merges here via PR |
| `release/vX.Y.Z` | Release prep — version bump + changelog stamp |
| `promote/YYYY-MM-DD` | Code-only promotion (no version change) |
| `hotfix/vX.Y.Z` | Cherry-pick urgent fixes to main |
| `rollback/vX.Y.Z` | Revert a bad release |

Contributors open PRs to `dev`. Maintainers promote `dev` to `main` when ready to release.

### Using `promote.sh`

The `scripts/promote.sh` script handles the full release lifecycle. It validates that the caller is a code owner before proceeding.

```bash
# Preview what would be promoted (safe, no side effects)
./scripts/promote.sh --dry-run

# Promote dev to main without a release
./scripts/promote.sh

# Create a patch release (0.29.1 → 0.29.2)
./scripts/promote.sh --patch

# Create a minor release (0.29.1 → 0.30.0)
./scripts/promote.sh --minor

# Cherry-pick a hotfix commit to main
./scripts/promote.sh --cherry-pick abc123

# Rollback the latest release
./scripts/promote.sh --rollback
```

### Post-Merge Automation

When a `release/v*` PR merges to `main`:

1. **tag-release.yml** extracts the version from the branch name and creates a `vX.Y.Z` tag
2. The tag push triggers **docker-publish.yml** which builds the Docker image, creates a GitHub Release with the Android APK, and sends a Discord notification

No manual tagging is required.

## Reporting Issues

Use the [issue templates](https://github.com/Morelitea/initiative/issues/new/choose) to file bug reports or feature requests.

## Security Vulnerabilities

Please **do not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

By contributing, you agree to the terms of the [Contributor License Agreement](./CLA.md).
