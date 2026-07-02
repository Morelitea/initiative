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

`backend/` hosts the FastAPI service; routers sit in `app/api`, config in `core`, persistence helpers in `db`, domain models in `models`, payloads in `schemas`, and business logic in `services`, with `main.py` as the uvicorn entry point. `frontend/src` stays feature-first (`api`, `components`, `features`, `pages`, `hooks`, `lib`, `types`). Dockerfiles plus the root `docker-compose.yml` wire Postgres, backend, and the nginx React build. User-facing documentation is a Zensical static site under `docs/en/` (build/preview with `zensical build`/`serve`; see `docs/en/admin/maintaining-these-docs.md`).

## Build, Test, and Development Commands

- `cd backend && uv sync` — create the `.venv` and install all runtime + dev deps from `uv.lock` ([uv](https://docs.astral.sh/uv/); `pyproject.toml` is the single source of truth, the lockfile pins exact versions).
- `cd backend && source .venv/bin/activate` — activate the synced env so bare `pytest`/`alembic`/`uvicorn`/`ruff` work, or prefix one-offs with `uv run` (e.g. `uv run pytest`).
- `cd backend && uvicorn app.main:app --reload` — run the API on http://localhost:8000.
- `cd backend && alembic upgrade head` — apply the latest database migrations (or run `python -m app.db.init_db` to migrate plus seed defaults).
- `cd backend && alembic revision --autogenerate -m "desc"` — generate a migration after SQLModel changes (**shared/`public` tables only** — guild-content tables are excluded from autogenerate; write those migrations by hand with `apply_to_all_guild_schemas`, see "Adding or changing tables").
- `cd frontend && pnpm install && pnpm dev` — launch the Vite dev server (uses `VITE_API_URL`, defaults to `http://localhost:8000/api/v1`).
- `docker-compose up --build` — start Postgres 17, backend, and the nginx SPA.
- `cd backend && pytest` / `ruff check app` and `cd frontend && pnpm lint` — run tests and linters. Tests are co-located alongside source files in `app/` (not in a separate `tests/` directory).

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
cd frontend && pnpm orval && pnpm biome format src/api/generated --write
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

#### `MIN_NATIVE_VERSION` (OTA native-compatibility floor)

The native (Capacitor) app receives web-bundle updates over the air: each Docker image ships the matching Capacitor bundle under `/app/ota`, served via `/api/v1/native/bundle/{manifest,download}`, and the app downloads it when the served version differs (see `useNativeUpdate`). The `MIN_NATIVE_VERSION` file at the project root is the **minimum native app (APK/IPA) version** the current web bundle requires — an OTA can only swap web assets, never native code.

- `scripts/promote.sh` bumps `MIN_NATIVE_VERSION` to the release version automatically when it detects a native change between `main` and `dev` (a `frontend/capacitor.config.ts` change, a committed change under `frontend/android`/`frontend/ios`, or an added/removed/bumped `@capacitor*`/`@capgo` dependency in `frontend/package.json`). Web-only releases leave it untouched.
- CI (`docker-publish.yml` `decide` job) compares `MIN_NATIVE_VERSION` against the previous tag: if it moved, it builds and attaches a fresh APK; if not, the **Android build is skipped** and the release ships Docker-only — existing installs update over the air.
- The app refuses a bundle whose `minNativeVersion` exceeds the installed native app version and prompts the user to update from the store/APK instead.
- Edge case the detector can't see: a native-affecting change that lands **only** via `pnpm-lock.yaml` (no `package.json` range change). Force a rebuild by editing `MIN_NATIVE_VERSION` manually that release.

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

**Namespaces**: `common`, `auth`, `nav`, `projects`, `tasks`, `documents`, `initiatives`, `settings`, `tags`, `guilds`, `import`, `notifications`, `stats`, `landing`, `errors`, `dates`, `access`, `command`, `counters`, `dashboard`, `events`, `properties`, `queues`, `trash`

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

They are **schema-per-guild native**: tenant models (initiatives, projects, tasks, documents, queues, counters, events, tags, uploads, …) exist only in per-guild Postgres schemas (`guild_<id>`), never in `public`. Every tenant factory routes the session to the right guild schema automatically (derived from its parent argument). Raw `session.add(<tenant model>)` in a test works when the row carries a `guild_id` or the session is already routed; an unroutable tenant write **raises** (fail-closed — see `app/testing/schema_harness.py`). For raw tenant *reads* on a fresh session, call `await route_session_to_guild(session, guild_id)` first.

Available factories:
- `create_user(session, **overrides)` — creates a `User` with unique email, hashed password, and default notification preferences
- `create_guild(session, creator=None, **overrides)` — creates a `Guild` and provisions its `guild_<id>` schema + roles; auto-creates a creator user if not provided
- `create_guild_membership(session, user=None, guild=None, role=GuildRole.member)` — links a user to a guild
- `create_initiative(session, guild, creator, **overrides)` — creates an `Initiative` with built-in roles and adds the creator as project manager
- `create_initiative_member(session, initiative, user, role_name="member")` — adds a user to an initiative with proper role lookup
- `create_project(session, initiative, owner, **overrides)` — creates a `Project` with owner grant
- `create_task(session, project, status_category=..., assignees=[...])`, `create_task_status`, `create_subtask`
- `create_document(session, initiative, creator)` — native document + owner grant
- `create_comment(session, author, task=... | document=...)`
- `create_tag(session, guild)`, `create_upload(session, guild, uploader)`
- `create_queue(session, initiative, creator)`, `create_queue_item(session, queue)`
- `create_counter_group(session, initiative, creator)`, `create_counter(session, group)`
- `create_calendar_event(session, initiative, creator)`, `create_property_definition(session, initiative)`, plus `create_{document,task,calendar_event}_property_value`

Auth helpers:
- `get_auth_token(user)` — returns a JWT string for the user
- `get_auth_headers(user)` — returns `{"Authorization": "Bearer <token>"}` dict

**The role seam — `acting_user`** (fixture in `conftest.py`, backed by `app.testing.Actor`/`make_actor`): every endpoint test states its actor's platform and guild roles through this one seam and gets an `Actor` dataclass back. With the real-role `client` fixture the request then executes as the real `app_user` → `platform_<tier>`/`guild_<id>` roles — RLS enforced, like production.

```python
from app.models.platform.guild import GuildRole

async def test_something(client, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    # a.user / a.headers / a.guild / a.membership / a.initiative / a.project
    response = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert response.status_code == 200

    # Second actor joining the same workspace at lower privilege:
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild,
                          initiative=a.initiative, initiative_role="member")
```

Platform role defaults: `owner` for public-path actors (`await acting_user()`), but `member` when `guild_role` is given — guild access must never depend on platform tier, and defaulting low keeps the suite proving that. Pass a platform tier explicitly (`await acting_user("support")`) to test platform ceilings. The superuser-backed `session` fixture is for setup/assertions only; `role_session` exercises the raw `app_user`/`app_admin` privilege boundary.

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

Copy `backend/.env.example`, set `DATABASE_URL`, `SECRET_KEY`, `AUTO_APPROVED_EMAIL_DOMAINS`, and optional `FIRST_OWNER_*` (legacy `FIRST_SUPERUSER_*` names still accepted), then run `alembic upgrade head` (or `python -m app.db.init_db`) so the schema is current and default settings/owner are seeded. The app connects through **three Postgres logins** (see the tenancy/RLS section): `DATABASE_URL` (the provisioning role — migrations + guild provisioning; the least-privilege `app_provisioner`, NOT a superuser — fresh docker-compose installs create it via the db init script; existing installs run `backend/scripts/create-provisioner.sql` once; the app warns at boot if it detects a superuser), `DATABASE_URL_APP` (`app_user`, RLS-enforced request path), and `DATABASE_URL_ADMIN` (`app_admin`, the policy-bound system engine); all three point at the same database. The SPA reads `VITE_API_URL`; align it with the reverse-proxy host in every environment. If enabling OIDC, ensure `APP_URL` is publicly reachable so computed callback URLs stay valid.

## Tenancy, Database Architecture & RLS

Tenancy is enforced in Postgres by **which role a request assumes** (`SET ROLE`), not by app-layer checks alone. There are two orthogonal dimensions — the per-guild schema/role, and the platform privilege ladder — both backed by real Postgres roles.

### The six authorization gates (security standard)

This is the canonical access-control model. Every path that reads or writes tooling data — REST, WebSocket, background job, realtime push — must honor all of it, and it must be enforced **at the database layer** (RLS preferred), not in app code alone. "Tools" = projects, queues, counters, calendar events, documents (and their content: tasks, comments).

Four nested gates, outermost → innermost:

1. **Guild** — no tooling data exists outside its `guild_<id>` schema. Enforced by schema-per-guild + `SET ROLE`.
2. **Initiative** — a user must **not** reach content of an initiative they are not in. This is the **hard isolation boundary** (it keeps sensitive data away from non-cleared members of the *same guild*). Enforced by RLS via `public.initiative_access(initiative_id, user_id, need_write)`.
3. **Initiative role** — within an initiative, a member's role dictates which tools they may engage and how.
4. **Tool sharing (DAC)** — per-resource `resource_grants` are the **final** privilege gate (`compute_*_permission` / `require_*_access`).

Two cross-cutting overrides sit above all four:

- **PAM** — platform roles may be **temporarily** granted scoped access via the DB tooling (time-bound, audited `access_grants`; `pam_read`/`pam_write` RLS legs). Never a standing bypass.
- **Guild admin** — **always** has read/write to **every** aspect of their guild, regardless of initiative membership or sharing (`is_request_guild_admin` / the `current_guild_role='admin'` RLS leg).

Two rules follow from this being a **DB-layer** standard: authorization is a property of the *current moment*, not of a connection or a cached snapshot (re-derive it when grant/role/membership/PAM change); and a non-DB-enforced channel (e.g. an out-of-band realtime push) must carry **no content it hasn't continuously authorized** — prefer a content-free signal + an RLS-gated refetch so the gates above are the only decision point. See [`history/realtime-authorization-design.md`](history/realtime-authorization-design.md).

### Three engines (Postgres logins) — [`session.py`](backend/app/db/session.py)

- **`app_user`** (`DATABASE_URL_APP`, `LOGIN NOINHERIT`, **RLS-enforced**) — the request path. Holds *no* standing access to any guild schema; every request `SET ROLE`s into a scoped role first.
- **`app_admin`** (`DATABASE_URL_ADMIN`, `LOGIN BYPASSRLS`) — the system engine: startup seeding, background jobs, and bootstrapping/lifecycle endpoints that can't run under a scoped role. This is PostgreSQL's textbook trusted-batch actor (BYPASSRLS is the documented mechanism for administrative sweeps); its boundary is **enumerated per-table GRANTs** (migration 0129) — a new shared table gives it nothing until a migration grants it. Guild schemas require `SET ROLE guild_<id>` (which **drops** the bypass), with `guild_role='admin'` for full-authority maintenance. No *user-facing* role ever bypasses RLS.
- **`app_provisioner`** (`DATABASE_URL`, `provisioning_engine`) — DDL only: migrations, `CREATE SCHEMA`/`CREATE ROLE`, guild provisioning. A least-privilege `NOSUPERUSER CREATEROLE` role that owns the app's objects — created by infrastructure, not app code (fresh installs: the compose `initdb` script; existing installs: `backend/scripts/create-provisioner.sql`, run once); `FORCE ROW LEVEL SECURITY` keeps even the owner policy-bound for DML. The app never holds Postgres superuser credentials — boot logs a warning if `DATABASE_URL` is a superuser/BYPASSRLS role.

### Schema-per-guild

Guild **content** (projects, tasks, documents, initiatives, queues, counters, calendar, tags, comments, …) lives in a **per-guild schema `guild_<id>`** — one schema per guild. Shared **identity/config** tables (`users`, `guilds`, `guild_memberships`, `guild_invites`, `app_settings`, `access_grants`, `oidc_*`) live in `public`.

- The canonical structure of a guild schema is [`alembic/guild/guild_schema.sql`](backend/alembic/guild/guild_schema.sql) — **autogenerated, never hand-edit**; regenerate with `python scripts/gen_guild_schema.py` (which reflects the Alembic-maintained `guild_template` schema) after any guild-scoped schema migration. The same DDL builds `guild_template` (migration 20260701_0126) and every `guild_<id>` (provisioning).
- Provisioning + per-guild roles live in [`schema_provisioning.py`](backend/app/db/schema_provisioning.py). `backfill_guild_schemas()` re-runs the idempotent provisioning for **every** guild on each boot, so a table/column/index added to `guild_schema.sql` reaches existing guilds automatically.
- **Guild isolation** is the schema boundary + `SET ROLE` (the request login role cannot reach any guild schema). On top of that, the guild **content** tables (projects, tasks, documents, queues, counters, calendar + children, property defs, and the polymorphic `resource_grants` — the single DAC table replacing the old per-resource `*_permissions`/`*_role_permissions`) carry **initiative-member RLS**: per-command PERMISSIVE policies that defer to one function, `public.initiative_access(initiative_id, user_id, need_write)` (initiative member OR guild admin OR PAM, read from the request GUCs). The **structural** initiative tables (`initiatives`, `initiative_members`, `initiative_roles`, `initiative_role_permissions`) are deliberately **not** initiative-scoped — they're guild-scoped by the schema boundary (you never query them outside a guild context; the membership table must not be gated by the membership check it backs, or RLS recurses; and own-row scoping there would break co-member rosters). The app layer uses the **same** function — [`membership.py`](backend/app/services/membership.py)'s `initiative_scope_clause` emits `func.initiative_access(...)`, so there's no parallel re-implementation. Policies live in [`alembic/guild/guild_rls.sql`](backend/alembic/guild/guild_rls.sql) — **autogenerated, never hand-edit**: `python scripts/gen_guild_rls.py` stamps them from the per-table `INITIATIVE_PATHS` registry in [`app/db/initiative_rls.py`](backend/app/db/initiative_rls.py) (the single source of truth — `INITIATIVE_SCOPED_TABLES`, and in turn `GUILD_SCOPED_TABLES`, derive from it) — applied by `apply_guild_rls` during provisioning (+ boot backfill); the function is created in `public` (no `SET search_path`, so it resolves the guild-local `initiative_members`; **not** `SECURITY DEFINER` — no RLS bypass). One consequence: a guild member who isn't in an initiative gets **404** (RLS hides the row), not 403, for that initiative's content.

### Roles assumed per request (`set_rls_context`)

- **Per-guild roles** `guild_<id>` (read/write its schema) and `guild_<id>_ro` (SELECT-only, for PAM *read* grants). Both inherit shared/`public` access from **`app_guild_base`**. The login roles are granted membership in every guild role **`WITH INHERIT FALSE`** — they can `SET ROLE` in but hold no standing access (fail-closed).
- **Platform-tier roles** `platform_<tier>` (member/support/moderator/admin/owner, `NOLOGIN`) + a shared **`platform_base`** floor; the public/platform path assumes `platform_<users.role>`.
- **Routing:** a **guild request** (`/g/{guild_id}/…`) → `SET ROLE guild_<id>` (or `_ro`), `search_path = guild_<id>, public`; a **public/platform request** → `SET ROLE platform_<tier>`, `search_path = public`. Each request resets to the login role (`SET ROLE none`) first, and the connection is reset on return to the pool.
- **No standing all-guild bypass for users, no superadmin.** The `app.is_superadmin` GUC and its policy legs were removed entirely (migration 0128). The only BYPASSRLS holder is the system engine (`app_admin`, the standard trusted-batch role — grant-bounded, never serving a user request as itself). A platform admin reaches a guild's data only via an explicit **break-glass** grant (below).

### Session Types (choose the right one)

| Session Dep | Engine / role assumed | When to use |
|---|---|---|
| `RLSSessionDep` (`get_guild_session`) | `app_user` → `SET ROLE guild_<id>`/`_ro` | Guild-scoped data under `/g/{guild_id}/…` (projects, tasks, documents, initiatives, tags, comments, task statuses, collaboration, imports). Pair with `GuildContextDep`. |
| `UserSessionDep` (`get_user_session`) | `app_user` → `SET ROLE platform_<tier>` | Authenticated public/platform path with no guild: list/reorder/leave guilds, cross-guild "my" (`/me/*`) reads, platform reads governed by `platform_<tier>` policies. |
| `AdminSessionDep` (`get_admin_session`) | `app_admin` (system engine: BYPASSRLS, grant-bounded) | Bootstrapping where the entity doesn't exist yet (create guild, accept invite), platform user management + `access_grants` endpoints (capability-gated), background jobs, startup seeding. Guild schemas only via `set_rls_context(guild_id=…)` — SET ROLE drops the bypass. |
| `SessionDep` (`get_session`) | `app_user`, login role (no `SET ROLE`) | Unauthenticated endpoints, or handlers that call `set_rls_context()` themselves after validating. |

### Path-based guild tenancy

The active guild is **addressed in the URL** (`/g/{guild_id}/…`), never server-held — the old `users.active_guild_id` column was **removed**. `get_guild_membership` (`GuildContextDep`) resolves the guild from the `Path` param and re-validates real membership **or** a live PAM/break-glass grant on every request (403 otherwise); the path is a selector, not a trust boundary. Cross-guild "my" views are dedicated `/api/v1/me/*` endpoints.

### Platform privilege ladder & capabilities

The 5-rung ladder (`member → support → moderator → admin → owner`, stored in `users.role`) maps to a capability set in [`capabilities.py`](backend/app/core/capabilities.py). Gate platform endpoints on a **capability** via `require_capability(...)`, never a role name; the frontend mirrors the capability strings in [`permissions.ts`](frontend/src/lib/permissions.ts) (reads backend-computed `UserRead.capabilities`). `config.manage` (owner-only) gates app config (OIDC, SMTP, branding, role labels, platform AI) under `/settings/admin`. The first/bootstrap user becomes `owner`; never leave the platform without a `config.manage` holder (`is_last_capability_holder`).

### Break-glass & PAM (cross-guild access without a standing bypass)

A user reaches a guild they don't belong to only through a **time-bound, per-guild, audited grant** (`access_grants` table, `/api/v1/access-grants`), routed through that guild's own `guild_<id>_ro`/`guild_<id>` roles + `pam_*` GUCs — never BYPASSRLS:

- **support / moderator** (`access.request`): request → an approver (`access.approve`) grants/denies → auto-expires. Read-only by default; a `read_write` grant edits *existing* content only (no authoring or member/permission management).
- **admin / owner** (`data.bypass`): self-issue a **break-glass** grant (`POST /access-grants/break-glass`) — created **and** self-approved in one step (the row is the audit trail), short TTL. Break-glass is deliberately **unlimited**: a read grant is full read-only of the guild; a `read_write` grant acts as a **full guild admin** for the window (routed as a synthetic guild-admin session). `data.bypass` is the *right to break glass*, not a standing bypass — with it removed, an admin reaches a guild only after clicking through.

### Rules for writing backend endpoints

1. **Default to `RLSSessionDep`** for any endpoint that reads/writes guild-scoped data; it requires `GuildContextDep` in the same signature (the guild comes from the `/g/{guild_id}` path).
2. **After every `session.commit()` that is followed by a database query** (including `session.refresh()`), call `await reapply_rls_context(session)`. A commit may release the connection back to the pool; the next query could land on a connection without the `SET ROLE`/GUCs.
3. **Use `UserSessionDep`** for authenticated cross-guild/platform reads so the request is `platform_<tier>`-scoped; reserve `AdminSessionDep` (the system engine) for bootstrapping/lifecycle/jobs that genuinely can't run under a scoped role — and remember a new shared table needs an explicit `GRANT … TO app_admin` before the system engine can touch it.
4. **Never use `SessionDep` for guild-scoped data** — without a `SET ROLE` it can't even see the guild schema (and shared-table reads run as the bare login role).
5. **Gate platform endpoints on `require_capability(...)`**; never re-introduce a request-path `is_superadmin=True` (that was Phase 3's whole removal).
6. **`set_rls_context()` uses `set_config()`** (not `SET` commands) so the assumed role and GUCs land on the same pooled connection as subsequent queries.

### Adding or changing tables

The path depends on **where the table lives**:

1. **Guild-scoped (content) table** — add/modify the SQLModel, then write the migration **by hand** applying the DDL to every guild schema: `apply_to_all_guild_schemas(op.get_bind(), "CREATE TABLE …", …)` from [`guild_migrations.py`](backend/app/db/guild_migrations.py) (targets `guild_template` + every `guild_<id>`; **never `public`** — autogenerate is filtered away from guild-content tables in `env.py`, and fresh installs have no public copies at all). Then do **both**:
   - **Regenerate the guild schema**: `alembic upgrade head`, then `python scripts/gen_guild_schema.py` (reflects `guild_template`; updates `guild_schema.sql`; `backfill_guild_schemas()` applies it to every `guild_<id>` on next boot, and provisioning uses it for new guilds). Isolation starts at the per-guild **schema + `SET ROLE`** — content tables do **not** get the old `guild_isolation`/`is_superadmin` policies.
   - **Classify it for initiative-member RLS — in ONE place.** Decide initiative-scoped vs guild-level:
     - *Initiative-scoped* (almost all content): add one entry to `INITIATIVE_PATHS` in [`app/db/initiative_rls.py`](backend/app/db/initiative_rls.py) describing how a row resolves its initiative (`direct()`, `via(parent, fk)`, a 2-hop helper, or a custom builder), then `python scripts/gen_guild_rls.py` to regenerate [`guild_rls.sql`](backend/alembic/guild/guild_rls.sql). `INITIATIVE_SCOPED_TABLES` and `GUILD_SCOPED_TABLES` **derive** from that registry, so you don't edit a second list. The table then carries the four PERMISSIVE `initiative_member_*` policies deferring to `initiative_access`.
     - *Guild-level* (guild-wide config, the structural initiative tables, own-row-only): add it to `GUILD_LEVEL_TABLES` in [`tenancy.py`](backend/app/db/tenancy.py) — exempt, protected only by the schema boundary. (`uploads` is the canonical example: no FK to any initiative.)

   Enforcement is automatic: `tenancy_test.py` fails CI if the new table is in neither bucket; `guild_rls_test.py` fails if an initiative-scoped table lacks its policies in a freshly provisioned schema, or if the committed `guild_rls.sql` drifts from the generator (a CI step in *Check Generated Types* regenerates + `git diff`s too). The [`membership.py`](backend/app/services/membership.py) `initiative_scope_clause` (→ `func.initiative_access`) stays for query-time filtering — same function, now backed by DB enforcement (a stale permission row still never grants access).

2. **Shared/platform table in `public`** (identity/config) — add it via Alembic migration with `ENABLE` + `FORCE ROW LEVEL SECURITY` and **role-scoped `TO platform_<tier>` policies** plus own-row predicates (`current_setting('app.current_user_id')`), following the Phase 2 pattern in [`20260616_0109_platform_role_rls.py`](backend/alembic/versions/20260616_0109_platform_role_rls.py). Make table `GRANT`s authoritative too (e.g. config tables owner-only to write). Gate the endpoints on the matching capability.

3. **`access_grants`** is platform-scoped (managed cross-guild) like `users`: its endpoints use `AdminSessionDep` with explicit capability + ownership checks, with `platform_<tier>` policies for the admin queue and an own-row policy for requesters.

4. **Renaming / dropping** — `DROP POLICY IF EXISTS …` and `DISABLE ROW LEVEL SECURITY` before the DDL; always provide a clean downgrade.

5. **Session-variable constants** (for the `public` shared-table policies and the PAM read path) — use these NULLIF-guarded forms in migration SQL:
   ```python
   # Always NULLIF-guard the cast: a PAM grantee (and any unset context) leaves the
   # value empty, and a bare ''::int raises and faults the WHOLE query for every
   # PERMISSIVE policy on the table. (See 20260530_0095, which retrofitted 13 legacy
   # guild_isolation policies on the public copies.)
   CURRENT_USER_ID    = "NULLIF(current_setting('app.current_user_id', true), '')::int"
   CURRENT_GUILD_ID   = "NULLIF(current_setting('app.current_guild_id', true), '')::int"
   CURRENT_GUILD_ROLE = "current_setting('app.current_guild_role', true)"      # 'admin' leg
   # PAM (time-bound, per-guild grants) — pam_guild_id is deliberately SEPARATE from
   # current_guild_id (a matching current_guild_id is treated as proof of membership,
   # which a grantee must not have):
   PAM_GUILD_ID = "NULLIF(current_setting('app.pam_guild_id', true), '')::int"
   PAM_READ     = "current_setting('app.pam_read', true) = 'true'"
   PAM_WRITE    = "current_setting('app.pam_write', true) = 'true'"
   ```
   > **Legacy note:** deployments that predate the v0.53.5 baseline squash still carry frozen `public` copies of guild-content tables (with old `guild_isolation` / `is_superadmin` / `*_pam_*` policies). They are **inert** — nothing reads or writes them, migrations no longer touch them, and fresh installs don't have them at all. They are kept only as a data-integrity backup until a future release drops them. Don't extend that pattern for new guild content; use the guild schema + roles.

6. **Verify after migration** as `app_user` (not the superuser): for a shared/platform table, confirm each tier hits its ceiling (a missing policy silently returns zero rows; a wrong one leaks). For guild content, `SET ROLE guild_<id>` and confirm only that guild's schema is reachable.

### Rules for writing frontend code

1. **React Query cache keys for the same data must match across components.** If the sidebar uses `["initiatives", guildId]` and a page uses `["initiatives", { guildId }]`, invalidation from one won't reach the other. Use prefix invalidation (`queryKey: ["initiatives"]`) when mutations should refresh all consumers.
2. **Guild context is in the URL path, not server-held.** Every guild-scoped request addresses its guild as `/api/v1/g/{guildId}/…`; there is no server-held "active guild" (the `users.active_guild_id` column was removed). Guild pages live under the `/g/$guildId` route tree and read the id from the path; `useActiveGuildId()` derives the current guild from the route (it is *not* the removed backend column). Cross-guild "my" views call the dedicated `/api/v1/me/*` endpoints. Separate tabs/windows can therefore operate in different guilds at once.
3. **Never use `localStorage` directly.** Import `getItem`, `setItem`, `removeItem` from `@/lib/storage` instead. The storage module uses an in-memory cache backed by Capacitor Preferences on native (preventing data loss when the OS clears localStorage) and delegates to localStorage on web. `initStorage()` hydrates the cache before React renders, so all reads are synchronous.

## Guild Architecture Notes

- Guilds are the primary tenancy boundary. Every user can join multiple guilds; the guild a request operates in is **addressed in the URL path** (`/g/{guild_id}/…`) — there is no server-held active guild (the `users.active_guild_id` column was removed). `GuildContextDep`/`RLSSessionDep` resolve the guild from the path and re-validate real membership (or a live PAM/break-glass grant) on every request, so a forged or stale path fails closed (403). Cross-guild "my" views are `/api/v1/me/*`. See the tenancy/RLS section for the schema-per-guild + role model.
- Guild membership has two roles (`admin`, `member`). Guild admins own memberships, invites, initiative/project configuration, and can delete their guild; they cannot delete users from the entire app. Keep server-side checks scoped to guild roles, not legacy global roles. A guild admin sees the whole guild via the `current_guild_role='admin'` RLS leg (and the guild role they `SET ROLE` into), not a bypass.
- **Platform roles are a 5-rung ladder** (`member` → `support` → `moderator` → `admin` → `owner`) resolved to a capability set in `backend/app/core/capabilities.py`, and each tier is a real `platform_<tier>` Postgres role the public path assumes. Gate platform endpoints on a capability via `require_capability(...)`, not a role name; the frontend reads the backend-computed `UserRead.capabilities` (mirror constants in `frontend/src/lib/permissions.ts`). App-wide configuration (OIDC, SMTP email, branding accents, role labels, platform AI) requires `config.manage` (owner-only) — these routes live under `/settings/admin`. The first/bootstrap user becomes `owner`. Never leave the platform without a `config.manage` holder (see `is_last_capability_holder`).
- **No standing all-guild bypass.** `data.bypass` (`admin`+`owner`) is **not** an ambient RLS bypass — it is the right to **self-issue a break-glass grant**. Cross-guild access (for any tier) is always a time-bound, per-guild, audited grant in `access_grants` (`/api/v1/access-grants`), routed through the guild's own `guild_<id>_ro`/`guild_<id>` roles — never BYPASSRLS. support/moderator use request → approve/deny → auto-expire (read-only by default, edit-existing only on `read_write`); admin/owner self-approve a break-glass grant (`POST /access-grants/break-glass`) that acts as a full guild admin for its window. See the tenancy/RLS section.
- `.env` supports `DISABLE_GUILD_CREATION`. When set to `true`, POST `/guilds/` must return 403 and the frontend should hide “Create guild” affordances, forcing new users to redeem invites issued by guild admins.
- Every new guild automatically **provisions its `guild_<id>` schema + per-guild roles** (`provision_guild_schema`), seeds a "Default Initiative", and makes the creator a guild admin. Be mindful when writing migrations or services so this invariant holds — guild deletion must drop the schema + roles (`deprovision_guild`) *and* clean up the shared rows (memberships, invites, OIDC mappings, access grants) that cascade off `public.guilds`.

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
