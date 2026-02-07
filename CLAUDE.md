# Repository Guidelines

## Frontend dev

This project uses pnpm, not npm.

## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Auto-syncs to JSONL for version control
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" -t bug|feature|task -p 0-4 --json
bd create "Issue title" -p 1 --deps discovered-from:bd-123 --json
bd create "Subtask" --parent <epic-id> --json  # Hierarchical subtask (gets ID like epic-id.1)
```

**Claim and update:**

```bash
bd update bd-42 --status in_progress --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task**: `bd update <id> --status in_progress`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`
6. **Commit together**: Always commit the `.beads/issues.jsonl` file together with the code changes so issue state stays in sync with code state

### Auto-Sync

bd automatically syncs with git:

- Exports to `.beads/issues.jsonl` after changes (5s debounce)
- Imports from JSONL when newer (e.g., after `git pull`)
- No manual export/import needed!

### GitHub Copilot Integration

If using GitHub Copilot, also create `.github/copilot-instructions.md` for automatic instruction loading.
Run `bd onboard` to get the content, or see step 2 of the onboard instructions.

### MCP Server (Recommended)

If using Claude or MCP-compatible clients, install the beads MCP server:

```bash
pip install beads-mcp
```

Add to MCP config (e.g., `~/.config/claude/config.json`):

```json
{
  "beads": {
    "command": "beads-mcp",
    "args": []
  }
}
```

Then use `mcp__beads__*` functions instead of CLI commands.

### Managing AI-Generated Planning Documents

AI assistants often create planning and design documents during development:

- PLAN.md, IMPLEMENTATION.md, ARCHITECTURE.md
- DESIGN.md, CODEBASE_SUMMARY.md, INTEGRATION_PLAN.md
- TESTING_GUIDE.md, TECHNICAL_DESIGN.md, and similar files

**Best Practice: Use a dedicated directory for these ephemeral files**

**Recommended approach:**

- Create a `history/` directory in the project root
- Store ALL AI-generated planning/design docs in `history/`
- Keep the repository root clean and focused on permanent project files
- Only access `history/` when explicitly asked to review past planning

**Example .gitignore entry (optional):**

```
# AI planning documents (ephemeral)
history/
```

**Benefits:**

- ✅ Clean repository root
- ✅ Clear separation between ephemeral and permanent documentation
- ✅ Easy to exclude from version control if desired
- ✅ Preserves planning history for archeological research
- ✅ Reduces noise when browsing the project

### CLI Help

Run `bd <command> --help` to see all available flags for any command.
For example: `bd create --help` shows `--parent`, `--deps`, `--assignee`, etc.

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ✅ Store AI planning docs in `history/` directory
- ✅ Run `bd <cmd> --help` to discover available flags
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems
- ❌ Do NOT clutter repo root with planning documents

For more details, see README.md and QUICKSTART.md.

## Project Structure & Module Organization

`backend/` hosts the FastAPI service; routers sit in `app/api`, config in `core`, persistence helpers in `db`, domain models in `models`, payloads in `schemas`, and business logic in `services`, with `main.py` as the uvicorn entry point. `frontend/src` stays feature-first (`api`, `components`, `features`, `pages`, `hooks`, `lib`, `types`). Dockerfiles plus the root `docker-compose.yml` wire Postgres, backend, and the nginx React build.

## Build, Test, and Development Commands

- `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` — install runtime deps.
- `cd backend && poetry install` — optional, but grabs dev tools (pytest, Ruff) defined in `pyproject.toml`.
- `cd backend && uvicorn app.main:app --reload` — run the API on http://localhost:8000.
- `cd backend && alembic upgrade head` — apply the latest database migrations (or run `python -m app.db.init_db` to migrate plus seed defaults).
- `cd backend && alembic revision --autogenerate -m "desc"` — generate a migration after SQLModel changes.
- `cd frontend && npm install && npm run dev` — launch the Vite dev server (uses `VITE_API_URL`, defaults to `http://localhost:8000/api/v1`).
- `docker-compose up --build` — start Postgres 17, backend, and the nginx SPA.
- `cd backend && pytest` / `ruff check app` and `cd frontend && npm run lint` — run tests and linters.

## Versioning

This project uses **semantic versioning** (semver) with a single source of truth: the `VERSION` file at the project root.

### How Versioning Works

- **Single source**: The `VERSION` file contains the current version (e.g., `0.1.0`)
- **Backend**: Reads VERSION file and exposes via `/api/v1/version` endpoint and OpenAPI schema
- **Frontend**: Vite injects VERSION as `__APP_VERSION__` constant, displayed in the sidebar footer
- **Docker**: VERSION is copied into the image and set as OCI labels

### Bumping the Version

Use the provided script to bump versions:

```bash
./scripts/bump-version.sh
```

This interactive script will:

1. Show the current version
2. Offer bump options: patch, minor, major, or custom
3. Update the VERSION file
4. Create a git commit with message `bump version to X.Y.Z`
5. Create a git tag `vX.Y.Z`

After running the script, push changes:

```bash
git push && git push --tags
```

### Manual Version Bump

If you prefer to bump manually:

```bash
# Update VERSION file
echo "0.2.0" > VERSION

# Commit and tag
git add VERSION
git commit -m "bump version to 0.2.0"
git tag v0.2.0
git push && git push --tags
```

### Semantic Versioning Guidelines

- **MAJOR** (1.0.0): Breaking changes, incompatible API changes
- **MINOR** (0.2.0): New features, backward-compatible additions
- **PATCH** (0.1.1): Bug fixes, backward-compatible fixes

### Changelog Maintenance

**IMPORTANT**: Always update `CHANGELOG.md` when making significant changes.

**Determining where to add changes:**

1. Check git log for recent "bump version to X.Y.Z" commits
2. If that version exists, it's already released
3. Add your changes to an `[Unreleased]` section at the top of the changelog
4. When the version is bumped, the unreleased section becomes the new version

**Example workflow:**

```bash
# Check recent history
git log --oneline --grep="bump version" -n 1

# If output shows "bump version to 0.7.2"
# Then 0.7.2 is released, add changes to [Unreleased]
```

**Changelog format:**

```markdown
## [Unreleased]

### Added

- New features go here

### Changed

- Modifications to existing features

### Fixed

- Bug fixes

## [0.7.2] - 2026-01-12

...existing released versions...
```

**Rules:**

- ✅ Update changelog for all feature additions, breaking changes, and bug fixes
- ✅ Use `[Unreleased]` section if the current VERSION has already been tagged
- ✅ Keep entries concise and user-focused
- ❌ Do NOT add changelog entries for minor refactoring or internal changes
- ❌ Do NOT put new changes under an already-released version number

### Docker Builds with Specific Versions

Build Docker images with version labels:

```bash
export VERSION=$(cat VERSION)
docker-compose build --build-arg VERSION=$VERSION
```

The version will be included as OCI image labels and available in the container.

## Coding Style & Naming Conventions

Python uses 4-space indentation, full type hints, `snake_case` modules/functions, and `PascalCase` SQLModel or schema classes; keep routing thin and push validation to `schemas` and `services`. React components are `PascalCase` files, hooks follow the `useThing` convention, and shared helpers live in `frontend/src/lib` or `api`. Ruff and ESLint must pass before opening a PR.

## Testing Guidelines

Write Pytest suites under `backend/tests`, exercising API routers with `httpx.AsyncClient` fixtures and covering RBAC, JWT flows, and initiative visibility rules. For new UI logic, add Vitest + Testing Library specs under the relevant feature folder (or `frontend/src/__tests__`); prioritize coverage for auth, project CRUD, and optimistic updates.

## Commit & Pull Request Guidelines

History favors short subjects (e.g., `MVP WIP 1`), so keep the first line imperative, ≤50 chars, and use additional lines for detail. Do not mention coding agents in commit messages. Separate backend, frontend, and infra changes when practical. PRs must describe the problem, list notable changes, call out schema or env updates, and attach screenshots/GIFs for UI tweaks plus the exact commands you ran for testing.

## Security & Configuration Tips

Copy `backend/.env.example`, set `DATABASE_URL`, `SECRET_KEY`, `AUTO_APPROVED_EMAIL_DOMAINS`, and optional `FIRST_SUPERUSER_*`, then run `alembic upgrade head` (or `python -m app.db.init_db`) so the schema is current and default settings/SUs are seeded. The SPA reads `VITE_API_URL`; align it with the reverse-proxy host in every environment. If enabling OIDC, ensure `APP_URL` is publicly reachable so computed callback URLs stay valid.

## Row-Level Security (RLS)

This project enforces PostgreSQL Row-Level Security at the database level. **Every backend endpoint must use the correct session type** to ensure data isolation between guilds.

### Session Types (choose the right one)

| Session Dep | When to use | RLS context set? |
|---|---|---|
| `RLSSessionDep` | Guild-scoped data endpoints (projects, tasks, documents, initiatives, tags, comments, task statuses, collaboration, imports, guild-scoped settings) | Yes — user + guild + role + superadmin |
| `UserSessionDep` | Cross-guild user operations (list guilds, reorder guilds, leave guild, leave eligibility) | Yes — user + superadmin only (no guild) |
| `AdminSessionDep` | Bootstrapping operations where the entity doesn't exist yet (create guild, accept invite), admin/auth/user management, background jobs, startup seeding | No — bypasses RLS entirely |
| `SessionDep` | Only for unauthenticated endpoints or where another dep manually calls `set_rls_context()` in the handler (e.g., guild admin endpoints that validate role first) | No — raw session, no RLS context |

### Rules for writing backend endpoints

1. **Default to `RLSSessionDep`** for any endpoint that reads/writes guild-scoped data. It requires `GuildContextDep` in the same endpoint signature.
2. **After every `session.commit()` that is followed by a database query** (including `session.refresh()`), call `await reapply_rls_context(session)`. Commits may release the connection back to the pool; the next query could land on a connection without RLS variables set.
3. **Use `AdminSessionDep`** for operations that can't work under RLS — e.g., creating a guild (the guild and membership don't exist yet, so INSERT...RETURNING triggers a SELECT policy that can't match).
4. **Never use `SessionDep` for guild-scoped data** — it has no RLS context and will either return all rows (if connected as superuser) or zero rows (if connected as `app_user`).
5. **`set_rls_context()` uses `set_config()`** (not `SET` commands) to guarantee execution on the same pooled connection as subsequent queries.
6. **New RLS policies** for new tables must be added via Alembic migration. Include `FORCE ROW LEVEL SECURITY` and add a superadmin bypass (`OR current_setting('app.is_superadmin', true) = 'true'`).

### Rules for writing frontend code

1. **React Query cache keys for the same data must match across components.** If the sidebar uses `["initiatives", guildId]` and a page uses `["initiatives", { guildId }]`, invalidation from one won't reach the other. Use prefix invalidation (`queryKey: ["initiatives"]`) when mutations should refresh all consumers.
2. **Always include the `X-Guild-ID` header** when calling guild-scoped endpoints. The `apiClient` interceptor handles this automatically via `activeGuildId`.

## Guild Architecture Notes

- Guilds are the primary tenancy boundary. Every user can join multiple guilds, and most API endpoints infer the active guild from the `X-Guild-ID` header (set by the SPA) or fall back to `users.active_guild_id`. Always include the guild header in new client calls when the route depends on guild context.
- Guild membership has two roles (`admin`, `member`). Guild admins own memberships, invites, initiative/project configuration, and can delete their guild; they cannot delete users from the entire app. Keep server-side checks scoped to guild roles, not legacy global roles.
- The bootstrap super user (ID `1`) is the only account allowed to change app-wide configuration (OIDC, SMTP email, branding accents, role labels). Those routes live under `/settings/admin` in the SPA and corresponding `/api/v1/settings/*` endpoints check for that ID explicitly.
- `.env` supports `DISABLE_GUILD_CREATION`. When set to `true`, POST `/guilds/` must return 403 and the frontend should hide “Create guild” affordances, forcing new users to redeem invites issued by guild admins.
- Every new guild automatically seeds a "Default Initiative" and makes the creator a guild admin. Be mindful when writing migrations or services so this invariant remains intact, especially when cascading deletes (guild deletion must clean up initiatives, projects, tasks, memberships, and settings).

## Docker Deployment

This project uses GitHub Actions to automatically build and publish Docker images to Docker Hub.

### How It Works

- **Automatic builds**: Triggered when you push version tags (e.g., `v0.1.1`)
- **Multi-arch support**: Builds for both `linux/amd64` and `linux/arm64` (Apple Silicon)
- **Multiple tags**: Creates `latest`, `1`, `1.2`, and `1.2.3` tags for flexibility
- **Version injection**: Builds Docker images with the correct VERSION from tags

### Setup Requirements

**First-time setup** (see `.github/DOCKER_SETUP.md` for details):

1. Create a Docker Hub access token with Read & Write permissions
2. Add GitHub secrets:
   - `DOCKERHUB_USERNAME` - Your Docker Hub username
   - `DOCKERHUB_TOKEN` - Your Docker Hub access token

### Deployment Workflow

The typical deployment process:

```bash
# 1. Bump version and create tag
./scripts/bump-version.sh

# 2. Push to trigger Docker build
git push && git push --tags

# 3. Monitor build progress
# Go to: GitHub → Actions → "Build and Push Docker Image"

# 4. Verify on Docker Hub
# Check: https://hub.docker.com/r/USERNAME/initiative/tags
```

The GitHub Actions workflow will:

- Build the Docker image with the new version
- Tag it appropriately (e.g., `latest`, `0.1`, `0.1.1`)
- Push to Docker Hub
- Support both x86_64 and ARM architectures

### Using Published Images

The easiest way to get started is with docker-compose:

```bash
# Copy the example configuration
cp docker-compose.example.yml docker-compose.yml

# Update SECRET_KEY and other settings as needed
nano docker-compose.yml

# Start the application
docker-compose up -d
```

This will:

- Pull the latest image from Docker Hub (`morelitea/initiative:latest`)
- Start PostgreSQL 17 database
- Configure automatic restarts and health checks
- Mount persistent volumes for uploads

Or pull and run manually:

```bash
docker pull morelitea/initiative:latest
docker pull morelitea/initiative:0.1.1  # specific version
```

### Manual Deployment

To trigger a build without a version tag:

1. Go to GitHub Actions → "Build and Push Docker Image"
2. Click "Run workflow"
3. Optionally specify a custom tag

### Important Notes

- Images include the VERSION file and expose version via `/api/v1/version`
- Frontend version checking will detect new deployments automatically
- Builds use GitHub Actions cache for faster subsequent builds
- Both backend and frontend are bundled in a single image

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
