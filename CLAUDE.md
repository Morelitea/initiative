# Repository Guidelines

## Frontend dev

This project uses pnpm, not npm.

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
- `cd backend && pytest` / `ruff check app` and `cd frontend && npm run lint` — run tests and linters. Tests are co-located alongside source files in `app/` (not in a separate `tests/` directory).

## Generated API Types (Orval)

Frontend TypeScript types and React Query hooks in `frontend/src/api/generated/` are auto-generated from the backend's OpenAPI spec using Orval. **Do not hand-edit these files.**

- `frontend/src/types/api.ts` re-exports all generated types and adds backward-compatible aliases (e.g., `Task = TaskListRead`).
- Generated files are committed to the repo so the frontend builds without a running backend.

**After changing backend schemas** (`backend/app/schemas/`), regenerate:

```bash
# Option 1: With a running backend
cd frontend && pnpm generate:api

# Option 2: Without a running backend
cd backend && python scripts/export_openapi.py ../frontend/openapi.json
cd frontend && pnpm orval
```

Always commit the regenerated output. CI enforces this — the `check-generated-types` job will fail if generated files don't match the current backend schemas.

**Key files:**
- `frontend/orval.config.ts` — Orval configuration
- `frontend/src/api/mutator.ts` — Axios wrapper that preserves auth/guild interceptors
- `frontend/scripts/generate-api.sh` — Generation script (supports `--from-spec <path>` for CI)
- `backend/scripts/export_openapi.py` — Exports OpenAPI JSON without a running server

## Versioning

This project uses **semantic versioning** (semver) with a single source of truth: the `VERSION` file at the project root.

### How Versioning Works

- **Single source**: The `VERSION` file contains the current version (e.g., `0.1.0`)
- **Backend**: Reads VERSION file and exposes via `/api/v1/version` endpoint and OpenAPI schema
- **Frontend**: Vite injects VERSION as `__APP_VERSION__` constant, displayed in the sidebar footer
- **Docker**: VERSION is copied into the image and set as OCI labels

### Releasing a Version

Releases are managed by `scripts/promote.sh`, which creates a PR from `dev` to `main` with the version bump and changelog stamp. Only code owners (@jordandrako, @LeeJMorel) can run this script.

```bash
# Patch release (0.29.1 → 0.29.2)
./scripts/promote.sh --patch

# Minor release (0.29.1 → 0.30.0)
./scripts/promote.sh --minor

# Major release (0.29.1 → 1.0.0)
./scripts/promote.sh --major

# Preview without making changes
./scripts/promote.sh --dry-run
```

After the release PR merges to `main`, `tag-release.yml` auto-creates the version tag, which triggers the Docker build and GitHub Release.

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
- ✅ Update the changelog **before** creating a PR, not after
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

## Internationalization (i18n)

All user-facing strings must be externalized for localization. **Never hardcode user-visible text in components or API error responses.**

### Frontend: react-i18next

Translation files live in `frontend/public/locales/en/<namespace>.json`. The app uses `i18next-http-backend` to lazy-load namespaces on first use.

**Namespaces**: `common`, `auth`, `nav`, `projects`, `tasks`, `documents`, `initiatives`, `settings`, `tags`, `guilds`, `import`, `notifications`, `stats`, `landing`, `errors`, `dates`

**Rules:**

1. **Use `useTranslation` in components** — call `const { t } = useTranslation("<namespace>")` and replace all hardcoded strings with `t("key")`.
2. **Cross-namespace references** use the `namespace:key` syntax — e.g., `t("common:loading")` from within a component using the `auth` namespace.
3. **Interpolation** uses `{{variable}}` syntax in JSON — `t("register.joiningGuild", { guildName })` maps to `"You're joining {{guildName}}."`.
4. **Plurals** use `_one`/`_other` suffixes in JSON — `{ "tasksArchived_one": "{{count}} task archived", "tasksArchived_other": "{{count}} tasks archived" }`.
5. **API error handling** — use `getErrorMessage(error, "namespace:fallbackKey")` from `@/lib/errorMessage` instead of displaying raw `detail` strings. This maps backend error codes to localized messages via `errors.json`.
6. **Utility functions outside React** — pass the `t` function as a parameter: `export const getLabel = (value: string, t: TFunction) => t(\`dates:status.${value}\`)`.
7. **Add new keys** to the appropriate namespace JSON file when adding new UI text. Keep keys organized with dot-notation grouping (e.g., `login.title`, `login.subtitle`).

```tsx
// Component pattern
const { t } = useTranslation("projects");
<CardTitle>{t("createProject.title")}</CardTitle>
<Input placeholder={t("createProject.namePlaceholder")} />
<Button>{submitting ? t("common:submitting") : t("common:save")}</Button>

// Error handling pattern
import { getErrorMessage } from "@/lib/errorMessage";
setError(getErrorMessage(err, "projects:createProject.error"));

// Toast pattern
toast.success(t("projects:projectCreated"));
```

### Backend: Error code constants

All `HTTPException` detail strings must use constants from `backend/app/core/messages.py` instead of inline strings. These constants are machine-readable codes (e.g., `EMAIL_ALREADY_REGISTERED`) that the frontend maps to localized messages.

**Rules:**

1. **Add new constants** to the appropriate class in `messages.py` (`AuthMessages`, `GuildMessages`, `OidcMessages`, or create new classes as needed).
2. **Use constants in HTTPException** — `raise HTTPException(status_code=400, detail=AuthMessages.INCORRECT_CREDENTIALS)`.
3. **Map codes in `errors.json`** — add a corresponding entry in `frontend/public/locales/en/errors.json` so the frontend can display a localized message.
4. **Tests assert on constants** — use `assert response.json()["detail"] == "EMAIL_ALREADY_REGISTERED"`, not substring matching on human-readable text.

## Coding Style & Naming Conventions

Python uses 4-space indentation, full type hints, `snake_case` modules/functions, and `PascalCase` SQLModel or schema classes; keep routing thin and push validation to `schemas` and `services`. React components are `PascalCase` files, hooks follow the `useThing` convention, and shared helpers live in `frontend/src/lib` or `api`. Ruff and ESLint must pass before opening a PR.

## Testing Guidelines

Tests are co-located next to their source files using a `_test.py` suffix (e.g., `app/services/guilds_test.py` tests `app/services/guilds.py`). Shared test factories live in `app/testing/factories.py` and are re-exported from `app/testing/__init__.py`. The root `backend/conftest.py` provides session, client, and auth fixtures. Run all tests with `cd backend && pytest` (testpaths is set to `app` in `pytest.ini`). For new UI logic, add Vitest + Testing Library specs under the relevant feature folder (or `frontend/src/__tests__`); prioritize coverage for auth, project CRUD, and optimistic updates.

### Running Tests

```bash
# Run all backend tests
cd backend && pytest

# Run tests for a specific module
cd backend && pytest app/services/guilds_test.py

# Run tests for a whole directory
cd backend && pytest app/api/v1/endpoints/

# Run only unit or integration tests
cd backend && pytest -m unit
cd backend && pytest -m integration

# Run tests for files you've changed (vs main)
cd backend && ./scripts/test-changed.sh

# Run tests for staged files only
cd backend && ./scripts/test-changed.sh --staged

# Run all frontend tests
cd frontend && pnpm test:run

# Run frontend tests in watch mode
cd frontend && pnpm test

# Run frontend tests for files you've changed (vs main)
cd frontend && ./scripts/test-changed.sh

# Run frontend tests for staged files only
cd frontend && ./scripts/test-changed.sh --staged
```

### Test Factories

Both backend and frontend provide factory functions for creating test data with sensible defaults. Always use these instead of hand-crafting test objects.

**Backend factories** live in `app/testing/factories.py` and are re-exported from `app/testing/__init__.py`. They are async functions that persist models to the test database and accept keyword overrides for any field.

Available factories:
- `create_user(session, **overrides)` — creates a `User` with unique email, hashed password, and default notification preferences
- `create_guild(session, creator=None, **overrides)` — creates a `Guild`; auto-creates a creator user if not provided
- `create_guild_membership(session, user=None, guild=None, role=GuildRole.member)` — links a user to a guild
- `create_initiative(session, guild, creator, **overrides)` — creates an `Initiative` with built-in roles and adds the creator as project manager
- `create_initiative_member(session, initiative, user, role_name="member")` — adds a user to an initiative with proper role lookup
- `create_project(session, initiative, owner, **overrides)` — creates a `Project` with owner permission

Auth helpers:
- `get_auth_token(user)` — returns a JWT string for the user
- `get_auth_headers(user)` — returns `{"Authorization": "Bearer <token>"}` dict
- `get_guild_headers(guild, user=None)` — returns `{"X-Guild-ID": "..."}` with optional auth

```python
from app.testing import create_user, create_guild, create_guild_membership, get_guild_headers
from app.models.guild import GuildRole

async def test_something(session, client):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/initiatives", headers=headers)
    assert response.status_code == 200
```

**Frontend factories** live in `src/__tests__/factories/` and are pure functions that return typed API response objects. They use auto-incrementing IDs and accept partial overrides via a spread pattern.

Available factories:
- `buildUser(overrides?)` / `buildUserPublic(overrides?)` / `buildUserGuildMember(overrides?)` — user objects at different detail levels
- `buildGuild(overrides?)` / `buildGuildInviteStatus(overrides?)` — guild and invite objects
- `buildInitiative(overrides?)` / `buildInitiativeMember(overrides?)` — initiative objects
- `buildProject(overrides?)` / `buildProjectPermission(overrides?)` — project objects
- `buildProjectTaskStatus(overrides?)` / `buildDefaultTaskStatuses(projectId?)` — task status objects (the latter returns all four default statuses)
- `buildTask(overrides?)` / `buildTaskListResponse(items?)` / `buildTaskAssignee(overrides?)` — task objects
- `buildTag(overrides?)` / `buildTagSummary(overrides?)` — tag objects
- `buildDocumentSummary(overrides?)` — document objects
- `buildComment(overrides?)` — comment objects
- `buildNotification(overrides?)` — notification objects
- `resetFactories()` — resets all ID counters (called automatically in test setup)

```typescript
import { buildUser, buildGuild, buildProject, buildTask } from "@/__tests__/factories";

const user = buildUser({ full_name: "Alice" });
const guild = buildGuild({ role: "admin" });
const project = buildProject({ owner_id: user.id, name: "My Project" });
const task = buildTask({ project_id: project.id, priority: "high" });
```

Frontend tests also use MSW (Mock Service Worker) handlers in `src/__tests__/helpers/handlers/` to mock API responses, and custom render helpers (`renderWithProviders`, `renderPage`) from `src/__tests__/helpers/render.tsx`.

## Commit & Pull Request Guidelines

History favors short subjects (e.g., `MVP WIP 1`), so keep the first line imperative, ≤50 chars, and use additional lines for detail. Do not mention coding agents in commit messages. Separate backend, frontend, and infra changes when practical. PRs must describe the problem, list notable changes, call out schema or env updates, and attach screenshots/GIFs for UI tweaks plus the exact commands you ran for testing. **PRs must target the `dev` branch**, not `main`.

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

### Adding or updating tables (RLS policy checklist)

Every guild-scoped table **must** have RLS policies. When creating a new table or changing an existing table's relationships, follow this checklist:

1. **New guild-scoped table with `guild_id` column** — create an Alembic migration that:
   - `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY`
   - `ALTER TABLE <name> FORCE ROW LEVEL SECURITY`
   - Creates a `guild_isolation` policy (or command-specific `guild_select`, `guild_insert`, etc. if access rules differ per operation)
   - Includes a superadmin bypass: `OR current_setting('app.is_superadmin', true) = 'true'`

2. **New junction/association table without `guild_id`** (e.g., `task_tags`, `document_tags`) — use an `EXISTS` subquery through the related table that does have `guild_id`:
   ```sql
   CREATE POLICY guild_isolation ON junction_table
   FOR ALL
   USING (
       EXISTS (
           SELECT 1 FROM parent_table
           WHERE parent_table.id = junction_table.parent_id
           AND parent_table.guild_id = current_setting('app.current_guild_id', true)::int
       )
       OR current_setting('app.is_superadmin', true) = 'true'
   )
   WITH CHECK (...)  -- same predicate
   ```

3. **Initiative-scoped tables** — add a second `AS RESTRICTIVE` policy layer for initiative membership on top of the guild isolation policy. Reference `20260210_0046_initiative_scoped_rls.py` for the pattern.

4. **Renaming or dropping a table** — drop existing policies first (`DROP POLICY IF EXISTS ... ON ...`), then disable RLS before the DDL change. Re-create policies on the new table name if renaming.

5. **Adding `guild_id` to an existing table that lacked it** — backfill the column, then add RLS policies in the same migration.

6. **Session variable constants** — use these in migration SQL:
   ```python
   CURRENT_GUILD_ID = "current_setting('app.current_guild_id', true)::int"
   CURRENT_USER_ID  = "NULLIF(current_setting('app.current_user_id', true), '')::int"
   CURRENT_GUILD_ROLE = "current_setting('app.current_guild_role', true)"
   IS_SUPERADMIN = "current_setting('app.is_superadmin', true) = 'true'"
   ```

7. **Downgrade function** — always include `DROP POLICY IF EXISTS` and `ALTER TABLE ... DISABLE ROW LEVEL SECURITY` so rollbacks are clean.

8. **Verify after migration** — connect as `app_user` (not the superuser) and confirm that queries only return rows for the active guild. A missing policy silently returns zero rows; a wrong policy leaks cross-guild data.

### Rules for writing frontend code

1. **React Query cache keys for the same data must match across components.** If the sidebar uses `["initiatives", guildId]` and a page uses `["initiatives", { guildId }]`, invalidation from one won't reach the other. Use prefix invalidation (`queryKey: ["initiatives"]`) when mutations should refresh all consumers.
2. **Always include the `X-Guild-ID` header** when calling guild-scoped endpoints. The `apiClient` interceptor handles this automatically via `activeGuildId`.
3. **Never use `localStorage` directly.** Import `getItem`, `setItem`, `removeItem` from `@/lib/storage` instead. The storage module uses an in-memory cache backed by Capacitor Preferences on native (preventing data loss when the OS clears localStorage) and delegates to localStorage on web. `initStorage()` hydrates the cache before React renders, so all reads are synchronous.

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
# 1. Create a release PR (bumps version + stamps changelog)
./scripts/promote.sh --patch   # or --minor / --major

# 2. Merge the release PR on GitHub

# 3. tag-release.yml auto-creates the version tag
#    docker-publish.yml builds, publishes, and notifies

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
