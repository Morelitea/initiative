# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Template document dropdown in CreateDocumentDialog not showing templates accessible via role-based permissions (only showed templates with explicit user permissions)
- Document/attachment uploads returning 422 error due to hardcoded `Content-Type: application/json` header overriding FormData auto-detection

## [0.31.2] - 2026-02-19

### Added

- Centralized query key invalidation helpers (`frontend/src/api/query-keys.ts`) with domain-specific functions for consistent cache management

### Changed

- Migrated ~70 frontend files from manual `apiClient` calls to Orval-generated functions and React Query hooks
  - Pages: all project, task, document, initiative, settings, and user settings pages
  - Components: sidebar, comment section, import dialogs, bulk edit dialogs, task checklist, notifications
  - Hooks: tags, roles, AI settings, interface colors, version check, push notifications, realtime updates
  - Route loaders: all `ensureQueryData` calls updated to use generated fetchers and query keys
- Centralized frontend API query hooks into domain-specific hook files (`useDocuments`, `useProjects`, `useInitiatives`, `useComments`, `useNotifications`) following the `useTags` pattern — replaces inline `useQuery`/`useMutation` calls across pages with clean, reusable hooks that include error toasts and cache invalidation
- Created `usePagination` hook for reusable page/pageSize state management with URL search param sync
- Replaced manual query keys (e.g., `["projects"]`) with generated URL-based keys (e.g., `["/api/v1/projects/"]`)
- Replaced manual `queryClient.invalidateQueries()` calls with domain-specific helpers from `query-keys.ts`
- Orval config updated to `httpClient: "axios"` for clean return types (no discriminated union wrappers)
- API mutator updated to accept `AxiosRequestConfig` and prevent double URL prefixing with `baseURL: ""`
- Removed duplicate `TaskListResponse` and `DocumentListResponse` type definitions from `types/api.ts` in favor of Orval-generated versions
- Deleted `src/api/notifications.ts` — all consumers migrated to `useNotifications` hooks
- Centralized remaining inline queries — `GuildDashboardPage`, `MyProjectsPage`, `MyDocumentsPage` now use domain hooks (`useProjects`, `useInitiatives`, `useTasks`, `useRecentComments`, `useGlobalProjects`, `useGlobalDocuments`)
- Eliminated direct `useQueryClient` usage from pages/components — added `usePrefetchTasks`, `usePrefetchGlobalProjects`, `usePrefetchGlobalDocuments`, `usePrefetchDocumentsList`, `useSetDocumentCache`, `useCommentsCache`, and `useUpdateRoleLabels` hooks
- Added ESLint rule (`no-restricted-imports`) to prevent direct `useQuery`/`useQueryClient` imports outside `src/api/` and `src/hooks/`
- Migrated direct type imports from `@/types/api` to `@/api/generated/initiativeAPI.schemas` — types that exist directly in the generated Orval schemas are now imported from source, reducing reliance on the backward-compat alias layer

### Fixed

- Tasks endpoint returned no results when requesting tasks for a template project
- Subtask checklist items failed to load ("Unable to load checklist items right now") due to double-unwrapping of API responses in `useSubtasks` hook and `TaskChecklist` mutations

## [0.31.1] - 2026-02-18

### Fixed

- Translation files were cached by the browser across deploys, causing newly added i18n keys to render as raw strings — translation fetches now include a version query param for cache busting

## [0.31.0] - 2026-02-18

### Added

- **Home sidebar mode** — clicking the logo now shows a user-centric sidebar (Discord-style) with personal navigation links instead of guild content
  - My Tasks (existing, refactored)
  - Tasks I Created — cross-guild list of tasks you created, with inline assignee display
  - My Projects — cross-guild list of projects you have access to
  - My Documents — cross-guild list of documents you own
  - My Stats (existing)
- `created_by_id` column on Task model to track who created each task
- `GET /tasks/?scope=global_created` endpoint — lists tasks created by the current user across all guilds
- `GET /projects/global` endpoint — lists projects the user can access across all guilds with pagination, guild filter, and search
- `GET /documents/?scope=global` endpoint — lists documents owned by the current user across all guilds
- Sequential Alembic migration naming convention (`YYYYMMDD_NNNN`) for chronological sorting
- Access controls in Create Project and Create Document dialogs via a collapsible "Advanced options" accordion
  - Role-based permission grants: assign access by initiative role at creation time
  - User-based permission grants: assign access to specific members at creation time
  - "Add all initiative members" opt-out toggle for projects (replaces invisible auto-add behavior)
- Shared `CreateAccessControl` component for role/user permission pickers

### Changed

- Sidebar now switches between Home mode (non-guild routes) and Guild mode (guild routes) based on the current URL
- MyTasksPage refactored to use shared `useGlobalTasksTable` hook, `GlobalTaskFilters`, and `globalTaskColumns` — shared across My Tasks and Tasks I Created pages
- Creating a project no longer auto-adds all initiative members as read — permissions are now explicitly controlled via the create dialog
- Project creation notifications are now scoped to only users who were granted access

### Fixed

- Post-baseline Alembic migration detection no longer crashes on startup — `init_db` now checks for `app_user` role existence instead of exact revision match
- Guild admins and initiative managers now follow DAC (Discretionary Access Control) for documents and projects — these roles no longer grant implicit owner-level access to every resource
- Guild admins can now add themselves to initiatives and manage initiative membership (previously required being an initiative manager)
- Collaboration WebSocket endpoint now uses pure DAC — matches REST endpoint behavior instead of bypassing access checks for admins/managers
- Fixed `handle_owner_removal` crash (`AttributeError: role`) when removing a member from an initiative
- Documents tag tree view: selecting "Not tagged" now filters server-side with correct pagination instead of client-side filtering per page
- Documents tag tree view: selecting a tag with no matching documents no longer replaces the sidebar with the empty state card
- AppSidebar crash when initiative query data is not an array

## [0.30.1] - 2026-02-16

### Added

- Auto-generated frontend TypeScript types and React Query hooks from the backend OpenAPI spec using Orval
  - Generated files in `frontend/src/api/generated/` committed to the repo so the frontend builds without a running backend
  - `frontend/src/types/api.ts` now re-exports generated types with backward-compatible aliases (e.g., `Task = TaskListRead`)
  - Custom Axios mutator (`frontend/src/api/mutator.ts`) preserves existing auth/guild interceptors
  - `pnpm generate:api` script to regenerate from a running backend
- CI check (`check-generated-types` job) that fails when generated frontend types drift from backend schemas
- `backend/scripts/export_openapi.py` to export OpenAPI spec without a running server (used by CI)

### Changed

- Backend Pydantic schemas now use `ConfigDict(json_schema_serialization_defaults_required=True)` so optional fields with defaults appear as required in the OpenAPI spec, producing cleaner generated types
- `frontend/src/types/api.ts` replaced ~800 lines of hand-maintained type definitions with re-exports from Orval-generated types
- Excluded `src/api/generated/**` from ESLint (Orval generates function overloads that trigger `no-redeclare`)
- CI backend test scoping now treats `app/schemas/` as shared infrastructure, triggering a full test run when schemas change
- Guild Dashboard landing page at `/g/:guildId/` with project health, velocity chart, upcoming tasks, recent projects, and initiative overview
- Guild switching now navigates to the dashboard instead of preserving the previous sub-path
- "All Projects" and "All Documents" links in the sidebar between favorites and initiatives
- Composite database indexes for query performance: tasks (project + archived, due date + status, updated_at), guild memberships (user + guild), and documents (updated_at)
- Squashed all 76 Alembic migrations into a single idempotent baseline migration — fresh installs no longer require `docker/init-db.sh` to pre-create database roles
- `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` are now **required** environment variables (previously fell back to `DATABASE_URL`, which silently ran the app as superuser without RLS enforcement)
- RLS is now always enforced — removed the `ENABLE_RLS` configuration flag
- Migrations always run using `DATABASE_URL` (superuser), fixing the env.py URL override bug that caused migrations to use the wrong connection
- Reorganized backend security architecture into two centralized service modules:
  - `rls.py` — Mandatory Access Control: guild isolation, guild RBAC (admin-only writes), initiative membership, and initiative RBAC via PermissionKey
  - `permissions.py` — Discretionary Access Control: project/document-level read/write/owner permissions with visibility subqueries
- Centralized guild admin enforcement across all endpoints via `rls_service.is_guild_admin()` and `rls_service.require_guild_admin()`
- Moved initiative security checks (`is_initiative_manager`, `check_initiative_permission`, `has_feature_access`) from initiatives service to `rls.py` (backward-compatible re-exports preserved)
- Replaced duplicated permission logic in endpoint files (projects, documents, tasks, tags, imports, collaboration) with shared helpers from `permissions.py`
- Consolidated visibility subquery patterns (`visible_project_ids_subquery`, `visible_document_ids_subquery`) to eliminate duplication across listing endpoints

### Removed

- `ENABLE_RLS` environment variable — RLS is always active; remove this from your `.env` if present
- `init_models()` backwards-compatibility alias (use `import app.db.base` directly)
- `docker/init-db.sh` — database role creation is now handled by the baseline migration itself
- 76 individual migration files replaced by single baseline (existing v0.30.0 databases upgrade seamlessly)

### Upgrade Notes

- **From v0.30.0**: No action needed — the baseline migration is a no-op for existing databases. You can safely remove `docker/init-db.sh` if present.
- **From pre-v0.30.0 (v0.14.1–v0.29.x)**: The application will detect the old schema and exit with instructions. Run the upgrade script before starting:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/Morelitea/initiative/main/scripts/upgrade-to-baseline.sql \
    -o upgrade-to-baseline.sql
  psql -v ON_ERROR_STOP=1 -f upgrade-to-baseline.sql "$DATABASE_URL"
  ```
  If psql is not available on your host (e.g. Synology, Unraid), pipe through the Postgres container:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/Morelitea/initiative/main/scripts/upgrade-to-baseline.sql | \
    docker exec -i initiative-db psql -v ON_ERROR_STOP=1 -U initiative -d initiative
  ```
  Then restart the application. The baseline migration will create database roles, RLS policies, and grants automatically.

## [0.30.0] - 2026-02-15

### Added

- Full internationalization (i18n) infrastructure with react-i18next and namespace-based translation loading
  - 16 translation namespaces covering all app areas: auth, nav, projects, tasks, documents, settings, guilds, initiatives, tags, stats, import, notifications, landing, errors, dates, common
  - Language selector in user interface settings (infrastructure ready for additional languages)
  - User `locale` preference stored in database with Alembic migration
  - Backend email i18n with JSON-based template loader and `{{variable}}` interpolation
  - Backend error code constants (`messages.py`) mapped to frontend-localized messages via `errors.json`
- All user-facing strings externalized across the entire application:
  - Auth flow (login, register, password reset, email verification)
  - Navigation, sidebar, and guild switcher
  - Project CRUD, settings, permissions, and kanban/table/timeline views
  - Task editing, assignments, recurrence, priorities, and status management
  - Document editor toolbar, comments, mentions, and emoji picker
  - Initiative and guild management, member tables, and invite flows
  - User settings (profile, security, notifications, interface, import/export)
  - Platform admin pages (users, settings, OIDC configuration)
  - Statistics and reporting pages
  - Landing page with all marketing copy
  - Email templates (verification, password reset, task assignment, mentions, overdue notifications)
- Spanish (es) locale — complete translations for all 16 frontend namespaces and backend email templates (these are AI generated translations, contributions wanted)
- Locale-aware AI content generation (subtasks, descriptions, document summaries respond in user's language)
- `useDateLocale` hook for date-fns locale resolution across the app
- Locale key parity test (vitest) to catch missing/extra translation keys in CI

## [0.29.1] - 2026-02-13

### Fixed

- Hotfix docker entry script

## [0.29.0] - 2026-02-13

### Added

- OIDC claim-to-role mapping: automatically assign users to guilds and initiatives based on OIDC token claims (e.g., `groups`, `realm_access.roles`) on every login
  - Configurable claim path and mapping rules in Platform Settings > Auth
  - Supports guild and initiative target types with role selection
  - OIDC-managed memberships tracked separately from manual assignments; manual memberships are never overwritten
  - Stale OIDC-managed memberships automatically removed when claims change
- OIDC refresh token periodic re-sync: stores encrypted refresh tokens and periodically re-fetches userinfo claims in the background, keeping guild/initiative memberships in sync without requiring re-login
  - 5-minute poll cycle with 15-minute per-user sync interval
  - Automatic token rotation support; graceful handling of revoked tokens
  - `offline_access` added to default OIDC scopes for refresh token issuance
- Extracted background task runner into dedicated `background_tasks.py` module
- PKCE (S256) support for OIDC authentication, required by many identity providers
- Multi-sort support for task list API (`sort_by=date_group,due_date&sort_dir=asc,asc`)
- New cinematic landing page with parallax starfield, scroll-driven animations, interactive screenshot lightbox, and dark/light theme support
- No-guild empty state for users with no guild membership after login, with options to create a guild, redeem an invite, or log out
- "Source" column in guild and initiative member tables showing whether membership is managed by OIDC or manual

### Changed

- Renamed `OIDC_DISCOVERY_URL` env variable to `OIDC_ISSUER` (old name still works as fallback); issuer URL no longer requires `/.well-known/openid-configuration` suffix
- Guild deletion now uses a name-confirmation dialog instead of browser prompt
- Logout now clears the React Query cache to prevent stale data when switching accounts

### Fixed

- Role-based write users now appear in task assignee dropdowns (previously only explicit user permissions were considered)
- My Tasks page now sorts by date group (overdue, today, this week, this month, later) then by due date, matching the visual grouping order
- `BEHIND_PROXY=true` now passes `--proxy-headers` and `--forwarded-allow-ips` to Uvicorn so real client IPs appear in logs and `request.client.host` (#92)
- Users with no guild membership no longer get 500 errors; backend returns 403 with descriptive message
- Documents on project dashboard are now filtered by user's document-level permissions (guild admins see all)
- Project settings button in sidebar now correctly appears for users with role-based write access
- Removing a user from a guild or initiative now clears their task assignments
- OIDC sync membership removal now cleans up task assignments
- Fixed loading state flicker on no-guild screen caused by `useGuilds` dependency cycle

## [0.28.0] - 2026-02-11

### Added

- Server-side pagination for tasks: `GET /tasks/` now accepts `page`, `page_size`, `sort_by`, and `sort_dir` query params, returning paginated results with total count (`page_size=0` returns all for drag-and-drop views)
  - Server-side sorting for tasks with support for title, due date, start date, priority, created/updated timestamps, and manual sort order
  - Pagination and server-side sorting controls on My Tasks page and tag tasks table, with page synced to URL and hover prefetching
- Server-side pagination and sorting for documents: `GET /documents/` now accepts `page`, `page_size`, `sort_by`, and `sort_dir` query params, returning paginated and sorted results with total count
  - `GET /documents/counts` lightweight endpoint returning per-tag document counts for the tag tree sidebar
  - Pagination controls (prev/next, page size selector, page in URL) for all three document views (list, grid, tags)
  - Data prefetching on hover over pagination buttons for instant page transitions
- Role-based access control for projects and documents: grant read or write access to an entire initiative role as well as adding users individually
  - Role Access section in project and document settings pages for managing role-based permissions
  - Bulk role access management: grant or revoke role-based permissions across multiple selected documents at once
  - `my_permission_level` field in project and document API responses indicating the current user's effective access level
- Persistent storage abstraction (`storage.ts`) backed by Capacitor Preferences on mobile and localStorage on web, preventing data loss when mobile OS clears localStorage under memory pressure

### Changed

- Project settings page reorganized into tabbed layout (Details, Access, Task statuses, Advanced)
- Document settings page reorganized into tabbed layout (Details, Access, Advanced)
- Bulk edit access dialog restructured into Roles and Users tabs, each with grant/revoke action selector
- All frontend localStorage usage migrated to the new storage abstraction (~15 files)

## [0.27.0] - 2026-02-10

### Added

- Initiative-scoped Row-Level Security: users must be an initiative member to see its data (initiatives, projects, documents, roles). Guild admins and superadmins bypass this layer.

### Fixed

- My Stats page returning all zeros after RLS enforcement (endpoint now uses UserSessionDep for proper RLS context)
- User profile and self-update endpoints returning empty initiative roles under RLS enforcement
- Missing `guild_id` on initiative member records when creating initiatives or adding members, causing members to be invisible under RLS
- Stale initiative data returned after create/update due to SQLAlchemy identity map caching
- 64 pre-existing test failures caused by test infrastructure not keeping up with RLS, DAC, and role system changes

## [0.26.0] - 2026-02-08

### Added

- Per-channel notification preferences: independent Email and Mobile App (push) toggles for each notification category
- Email notifications for mentions, comments, and replies (previously only had push and in-app)
- Mobile App column on notification preferences page (shown when FCM is enabled)

### Changed

- In-app bell notifications now always fire regardless of user preferences
- Notification preferences page redesigned as a table with Email and Mobile App columns

### Fixed

- Mentions preference (`notify_mentions`) was missing from user update schemas, preventing it from being changed via API

## [0.25.5] - 2026-02-07

### Added

- Email column in project and document access tables for easier member identification

### Fixed

- Task status editing no longer crashes with 500 error for custom roles
- Task status management now uses project-level write access (DAC) instead of requiring initiative manager role
- Guild admins can now see all guild members in the Users settings table (was only visible to platform admins)

## [0.25.4] - 2026-02-07

### Fixed

- Attempt: My Tasks page now shows tasks from all guilds the user belongs to, not just the active guild (RLS SELECT policies now check membership instead of active guild)

## [0.25.3] - 2026-02-07

### Fixed

- Mobile deep links now correctly forward device token auth

## [0.25.2] - 2026-02-07

### Fixed

- OIDC login on mobile now issues a long-lived device token instead of a short-lived JWT, so sessions persist across app restarts

## [0.25.1] - 2026-02-07

### Fixed

- Tag badges now link to their tag detail page across all views (My Tasks, project table, Kanban, project previews, documents)
- Added tags column to My Tasks table
- Create project dialog no longer reopens after clicking cancel or create
- Make heading and filter styling more consistent across pages

## [0.25.0] - 2026-02-06

### Added

- **Row Level Security (RLS) enforcement** across all API endpoints
  - Database-level access control ensures users can only access data within their guild
  - All guild-scoped endpoints now set RLS context (user, guild, role) before querying
  - Super admin bypass via `app.is_superadmin` session variable
  - RLS policies added for tags, document_links, task_tags, project_tags, and document_tags tables
  - Guild table now has command-specific policies (SELECT/INSERT/UPDATE/DELETE) instead of a single blanket policy
  - Guild memberships allow cross-guild SELECT for own memberships (needed for guild list, leave checks)
  - NULLIF-safe policies prevent empty string cast crashes (fail-closed with 0 rows instead of 500 errors)

### Changed

- Admin endpoints now use dedicated admin database sessions (bypass RLS for cross-guild platform operations)
- Registration, invite acceptance, and account deletion use admin sessions (bootstrapping operations that span guilds)
- Database sessions pin their connection for the entire request lifetime to prevent RLS context loss after commits

### Upgrade Notes

**Docker deployments** should update their setup to enable RLS enforcement:

1. **Add the init script** — copy `docker/init-db.sh` from the repository into a `docker/` directory next to your `docker-compose.yml`. This script creates two PostgreSQL roles:
   - `app_user` — RLS-enforced, used for normal API queries
   - `app_admin` — BYPASSRLS, used for migrations and background jobs

2. **Update `docker-compose.yml`** — add the following to your `db` service:

   ```yaml
   services:
     db:
       environment:
         APP_USER_PASSWORD: ${APP_USER_PASSWORD:-app_user_password}
         APP_ADMIN_PASSWORD: ${APP_ADMIN_PASSWORD:-app_admin_password}
       volumes:
         - ./docker/init-db.sh:/docker-entrypoint-initdb.d/01-create-roles.sh
   ```

   And add these environment variables to your `initiative` service:

   ```yaml
   services:
     initiative:
       environment:
         # RLS-enforced connection (app_user role, no BYPASSRLS)
         DATABASE_URL_APP: postgresql+asyncpg://app_user:${APP_USER_PASSWORD:-app_user_password}@db:5432/initiative
         # Admin connection for migrations and background jobs (app_admin role, BYPASSRLS)
         DATABASE_URL_ADMIN: postgresql+asyncpg://app_admin:${APP_ADMIN_PASSWORD:-app_admin_password}@db:5432/initiative
   ```

   See `docker-compose.example.yml` for a complete reference.

3. **Fresh databases only** — the init script runs on first `docker-compose up` (when the postgres data volume is empty). For existing databases, the Alembic migration (`20260207_0040`) creates the roles automatically. You will still need to set `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` environment variables.

4. **Backward compatible** — if `DATABASE_URL_APP` is not set, the app falls back to `DATABASE_URL` and RLS remains inert (existing behavior).

## [0.24.0] - 2026-02-06

### Added

- Bulk edit tags for tasks and documents (add/remove modes)
- Bulk edit access permissions for documents (grant/revoke modes)
- Tag detail page now uses a tabbed layout (Tasks, Projects, Documents) with full filtering, sorting, and inline status/priority editing

### Fixed

- Duplicate rows appearing in task table when sorting with filters applied
- Guild switching no longer flashes back and forth between old and new guild before settling
- Tags now carry over when recurring tasks create their next instance

## [0.23.0] - 2026-02-05

### Added

- Tags view on Documents page for browsing documents by tag
  - Collapsible tag tree with document counts and hierarchical expand/collapse
  - Click to filter by tag, Ctrl/Cmd+Click for multi-select (OR filtering)
  - "Not tagged" filter for documents without any tags
  - Responsive layout: side panel on desktop, collapsible header on mobile
  - Tags view is now the default view mode (Tags / Grid / List)

### Fixed

- Multi-tab guild stability: opening different guilds in separate tabs no longer causes rapid switching or ping-pong loops
  - Removed server-side `active_guild_id` tracking (each tab derives guild from URL)
  - Removed cross-tab localStorage sync that caused cascading re-renders
  - Removed `POST /guilds/{id}/switch` endpoint (no longer needed with guild-scoped URLs)

## [0.22.0] - 2026-02-04

### Added

- Guild-scoped URLs for shareable cross-guild links
  - Routes changed from `/projects/47` to `/g/:guildId/projects/47`
  - Links can be shared directly without losing guild context
  - Old URLs automatically redirect to new format for backward compatibility
  - Cross-guild navigation on My Tasks page works without manual guild switching

## [0.21.0] - 2026-02-04

### Added

- Guild-scoped tags for tasks, projects, and documents
  - Create tags with custom names and colors via TagPicker component
  - Assign multiple tags to tasks, projects, and documents
  - Filter by tags in project tasks view, projects page, and documents page
  - Tags displayed on project cards, document cards, and task table rows
  - Tag browser in sidebar with nested hierarchy support (e.g., "books/fiction")
  - Tag detail page showing all entities with a specific tag
  - Tags preserved when duplicating tasks, projects, or documents
  - Case-insensitive unique names per guild
- Document wikilinks with `[[Document Title]]` syntax
  - Type `[[` in the editor to search for documents in the current initiative
  - Autocomplete shows existing documents, with option to create new ones
  - Resolved links display in blue; unresolved links display in grey/italic
  - Click links to navigate or create documents
  - Backlinks section shows documents that link to the current document
  - Document titles must be unique within each initiative

### Fixed

- Race condition in recording recent project views causing duplicate key errors

## [0.20.1] - 2026-02-03

### Changed

- Initiative settings members table now has separate Name and Email columns
- Removing a member from an initiative now shows a confirmation dialog warning that explicit access to all projects and documents will be removed

### Fixed

- Members table filter input now works correctly
- Users dropdown now refreshes when switching guilds (was showing stale data from previous guild)

## [0.20.0] - 2026-02-03

### Added

- Configurable role permissions per initiative
  - Four permission keys: `docs_enabled`, `projects_enabled`, `create_docs`, `create_projects`
  - Roles tab in Initiative Settings to manage role permissions
  - Create custom roles with configurable permissions
  - Rename and delete custom roles
  - Sidebar hides Docs/Projects based on role permissions
  - Create buttons hidden based on role permissions
  - Built-in PM role has locked permissions; Member role is configurable
  - Does not override DAC for project/document resources (direct links still work with explicit access)
- Document AI Summary feature
  - "Summarize with AI" generates 2-4 paragraph summaries of native documents
  - New side panel with tabs for AI Summary and Comments
  - Panel toggle button in document header
  - Summary persists when switching between tabs
  - Converts Lexical editor content to Markdown for better AI comprehension
- Uploadable file documents (PDF, Word, Excel, PowerPoint, text, HTML)
  - Upload files via "Upload file" tab in create document dialog
  - PDF viewer with zoom controls and continuous page scrolling
  - Office documents show download prompt (browser preview not supported)
  - 50 MB file size limit with client-side validation
- Lazy loading for document detail page (Editor and PDF viewer load on demand)
- Comment editing for authors
  - Users can edit their own comments on tasks and documents
  - Edit button appears next to Reply for author's own comments
  - Inline edit mode with Save/Cancel buttons
  - "(edited)" indicator shows when a comment has been modified

### Changed

- Document comments moved from inline section to side panel
- AI-generated subtasks and descriptions now include initiative and project names for better context
- Only guild admins and initiative project managers can pin/unpin projects
- Pin button is now hidden for users who cannot pin (instead of showing disabled)
- Refactored project access control to discretionary access control (DAC) model
  - Task assignments are automatically removed when a user loses write access (permission removed or downgraded to read)
  - Removed `members_can_write` toggle from projects
  - Added `read` permission level (owner, write, read)
  - Access is now determined solely by explicit permissions in the project_permissions table
  - On project creation, all initiative members are automatically granted read access
  - When a user leaves an initiative, their project permissions are cleaned up automatically
  - When a project owner is removed from an initiative, all initiative PMs get owner access
  - Project settings page now shows a permissions table instead of the old toggle + overrides UI
- Refactored document access control to discretionary access control (DAC) model
  - Added `owner` permission level to documents (owner, write, read)
  - Document creators automatically become owners with full management rights
  - Owners can manage permissions, delete, and duplicate documents without being initiative PMs
  - Added individual member management endpoints (POST/PATCH/DELETE) for document permissions
  - When a document owner is removed from an initiative, all initiative PMs get owner access
  - Document settings page now shows a permissions table instead of the old toggle UI

### Fixed

- Document editor no longer appears blank when collaboration mode is loading
- Collaboration now shows proper status progression: "Connecting..." → "Syncing..." → "Live editing"
- Fixed stuck "Syncing..." spinner after navigating between documents quickly
- Collaboration connection now automatically reconnects when dropped
- Error toast now appears when collaboration fails, with automatic fallback to autosave mode

## [0.19.1] - 2026-01-30

### Fixed

- Task filters now properly reset when navigating between projects

## [0.19.0] - 2026-01-30

### Added

- Guild sidebar context menu (right-click)
  - All members: View initiatives, Copy guild ID, Leave guild
  - Guild admins: View members, Invite members (creates & copies invite link), Create initiative, Guild settings
  - Leave guild checks eligibility (last admin, sole PM of initiatives) before allowing departure
  - Actions automatically switch to the target guild's context when needed

### Changed

- Migrated frontend routing from React Router to TanStack Router
  - Type-safe routing with validated route params and search params
  - Improved React Query integration for data prefetching
- Removed initiative filter from My Tasks page (was showing only active guild's initiatives, making it redundant)

### Fixed

- Switching guilds now properly refreshes project, initiative, and document lists
- Connect and login pages no longer require double-clicking to navigate on mobile
- Live collaboration and real-time updates now work on mobile apps

## [0.18.0] - 2026-01-28

### Added

- Platform admin blocker resolution for user deletion
  - New admin endpoints to delete guilds, promote guild members, and promote initiative members
  - Enhanced deletion eligibility response includes detailed blocker info with promotable members
  - Delete user dialog now shows "Resolve Blockers" step with inline actions
  - Admins can promote another member to guild admin or delete the guild entirely
  - Admins can promote another member to project manager for initiatives
  - Auto-advances to next step when all blockers are resolved
- PostgreSQL Row Level Security (RLS) for guild data isolation
  - Database-level access control ensures users can only access data within their current guild
  - Defense-in-depth protection in addition to application-level access controls
  - Denormalized `guild_id` columns added to all tier 2/3 tables for efficient policy evaluation
  - Automatic triggers maintain guild_id consistency when parent relationships change
  - New `RLSSessionDep` dependency for routes that need database-level access control
  - Admin bypass role (`app_admin`) for migrations and background jobs
- Role-based platform admin system with promote/demote functionality
  - Multiple users can now be platform admins (no longer limited to user ID 1)
  - Platform admins can promote/demote other users via Platform Users settings page
  - Protection against demoting the last platform admin
  - Platform roles and guild roles are now completely independent
  - Guild Users page now manages guild roles separately from platform roles
- `ENABLE_PUBLIC_REGISTRATION` environment variable to control public registration
  - When set to `false`, all new users must register via an invite link
  - Bootstrap (first user) registration is always allowed regardless of setting
  - Landing page and register page adapt UI based on this setting
- Platform admins can now create guilds when `DISABLE_GUILD_CREATION=true`
  - Regular users are still blocked from creating guilds when this flag is enabled
  - The `can_create_guilds` field in user responses now reflects platform admin status

### Changed

- **Docker users**: `DATABASE_URL_ADMIN` environment variable is now required for RLS migrations
  - RLS migrations need superuser privileges to create the `app_admin` role with `BYPASSRLS`
  - Add to your docker-compose: `DATABASE_URL_ADMIN: postgresql+asyncpg://postgres:${POSTGRES_PASSWORD:-initiative}@db:5432/initiative`
  - This URL uses the `postgres` superuser; the regular `DATABASE_URL` continues using the restricted `initiative` user
- Destructive actions now use confirmation dialogs instead of browser alerts

## [0.17.0] - 2026-01-27

### Added

- Switchable color themes with user preference persistence
  - Theme selector in Settings → Interface
  - Three built-in themes: Kobold (default indigo), Displacer (Catppuccin pastels), Strahd (Dracula gothic)
  - Extensible theme system for adding custom themes
  - Themes apply to both light and dark modes
- Spell check suggestions in document editor context menu
  - Right-click on misspelled words to see correction suggestions
  - Uses Typo.js with dictionaries loaded from CDN on first use
  - Works consistently across Chrome, Firefox, and other browsers
- Priority badge is now a clickable dropdown to change task priority inline

### Fixed

- Document page comments now wrap below editor at larger screen widths for better readability
- Past due dates now show green (success) when task is completed instead of always showing red
- Bulk edit dialog now correctly uses "Urgent" priority value instead of invalid "Critical"
- URLs in comments are now clickable and properly wrap instead of overflowing the container
- URLs in task descriptions (markdown) now properly wrap instead of overflowing
- Layout no longer disappears when navigating to lazy-loaded pages (shows spinner in content area)
- Version update popup no longer appears when client version is ahead of server
- Dismissed version popup no longer reappears on page refresh (persisted to localStorage)
- Fixed footer alignment in version update dialog
- Version dialog changelog now renders nested list items

## [0.16.0] - 2026-01-25

### Added

- Live collaborative document editing using Yjs CRDT
  - Multiple users can edit the same document simultaneously in real-time
  - Collaborator presence indicators showing who is currently editing
  - WebSocket-based synchronization with automatic reconnection
  - Graceful fallback to autosave mode if collaboration connection fails
  - New database column `yjs_state` stores collaborative document state

## [0.15.2] - 2026-01-24

### Fixed

- Mobile OIDC deep link handler now works from login page (was only active after authentication)

## [0.15.1] - 2026-01-24

### Added

- Mobile OIDC/SSO login support using deep links
  - OIDC authentication now works on the mobile app
  - Uses Capacitor Browser plugin to open system browser for OAuth flow
  - Custom URL scheme (`initiative://`) handles callback redirect
  - Mobile redirect URI displayed in auth settings page

### Fixed

- Document export now uses document title in filename instead of generic timestamp

## [0.15.0] - 2026-01-23

### Added

- Enabled speech-to-text plugin on document editor. Uses browser speech recognition APIs. Tested working on Chrome and Edge.
- Responsive document editor toolbar
  - Compact overflow menu on screens below 1024px with all formatting options
  - Full inline toolbar on larger screens
- Alignment buttons converted to a dropdown menu for a more compact toolbar

### Fixed

- Speech-to-text now normalizes transcripts across browsers (auto-spacing, auto-capitalization)
- Speech recognition preview bubble no longer hidden behind toolbar
- Android APK version now syncs with main VERSION file (was stuck at 1.0)

## [0.14.1] - 2026-01-23

### Added

- Licensed the project with AGPLv3

### Fixed

- Rolling recurrence now preserves the original due time instead of inheriting the completion timestamp

## [0.14.0] - 2026-01-22

### Added

- Enhanced comments with mentions, threading, and notifications
  - @mention syntax for users (`@[Name](id)`) with autocomplete popup
  - Entity mentions for tasks (`#task[Title](id)`), documents (`#doc[Title](id)`), and projects (`#project[Name](id)`)
  - Threaded replies with visual indentation (max 3 levels)
  - Reply button on each comment with inline reply form
- Comment notifications with intelligent deduplication
  - Notify users when mentioned in comments
  - Notify task assignees when their task is mentioned
  - Notify task assignees when someone comments on their task
  - Notify document authors when someone comments on their document
  - Users already notified via one mechanism won't receive duplicate notifications
- Mentions toggle in user notification settings

### Fixed

- Document editor: heading spacing, horizontal rule spacing, code background, url modal background

## [0.13.0] - 2026-01-21

### Added

- AI Integration with BYOK (Bring Your Own Key) support
  - Hierarchical settings: Platform -> Guild -> User with inheritance and override controls
  - Support for OpenAI, Anthropic, Ollama (local), and custom OpenAI-compatible providers
  - Test connection validates API keys and model names, fetches available models
  - Searchable model combobox with custom model name support
- AI-powered task features (when AI is enabled)
  - Generate description: AI button next to description field auto-generates task descriptions
  - Generate subtasks: AI button in subtasks section suggests actionable subtasks with selection dialog

### Changed

- Anthropic test connection now fetches models dynamically from their API instead of hardcoded list
- Model combobox now fetches available models automatically when opened (improved UX)

## [0.12.5] - 2026-01-20

### Added

- Pull-to-refresh on mobile app to refresh data without reloading the page (My Tasks, Projects, Project Detail, Initiatives)

### Fixed

- Android hardware back button now navigates through router history instead of exiting the app

### Changed

- Inverted app icon. Now when it's themed, its more legible.

## [0.12.4] - 2026-01-18

### Fixed

- FirebaseRuntime plugin now registers before Capacitor bridge initialization

## [0.12.3] - 2026-01-17

### Fixed

- Push notifications now work on self-hosted deployments (fixed FCM config URL)

## [0.12.2] - 2026-01-17

### Fixed

- Task position no longer changes when updating status via dropdown in table view
- Safe area insets now work correctly on Samsung One UI devices

## [0.12.1] - 2026-01-17

### Fixed

- Server crash on startup due to missing request parameter in FCM config endpoint rate limiter

## [0.12.0] - 2026-01-17

### Added

- Push notifications for mobile devices via Firebase Cloud Messaging (FCM)
- Runtime Firebase initialization - no APK rebuild required for self-hosted instances
- Five notification channels for Android: Task Assignments, Initiative Invites, New Projects, User Approvals, and Mentions
- Custom white notification icon for proper Android notification tray display
- Push notification settings in user notification preferences
- Automatic FCM config endpoint for mobile app initialization (`/api/v1/settings/fcm-config`)
- Push token management with automatic cleanup of invalid tokens

## [0.11.1] - 2026-01-16

### Fixed

- Device tokens now display actual device name (e.g., "Jordan's S25 Ultra") instead of generic "Mobile Device"

## [0.11.0] - 2026-01-16

### Added

- Capacitor mobile app support for iOS and Android
- Device authentication tokens for persistent mobile login (never expire)
- Server URL configuration page for connecting to self-hosted instances
- Safe area handling for edge-to-edge display on Android
- Android APK automatically built and attached to GitHub releases
- Device token management in user settings (view and revoke mobile sessions)

### Changed

- Renamed "API Keys" settings tab to "Security" (now includes device management)
- Mobile auth uses device tokens instead of expiring JWTs
- Token storage uses native Preferences API for persistence on mobile

## [0.10.0] - 2026-01-14

### Added

- Task import from external platforms (Todoist CSV, Vikunja JSON, TickTick CSV)
- Import settings page with extensible platform support (Trello, Asana coming soon)
- Section/bucket-to-status mapping with smart suggestions based on names
- Subtask and priority mapping during import

## [0.9.0] - 2026-01-14

### Added

- Task archival feature: archive tasks to hide them from default views
- "Show archived" filter toggle in project task views
- Archive/Unarchive button on task detail page
- "Archive done tasks" bulk action in table view and kanban done columns
- Archive button in bulk selection panel for archiving multiple tasks at once
- Confirmation dialog for archive actions showing task count

## [0.8.0] - 2026-01-13

### Added

- @mention support for tagging initiative members in documents
- Notifications when users are mentioned in documents
- User preference to enable/disable mention notifications
- Autosave for documents with toggle checkbox (enabled by default)

### Changed

- Document editor upgraded to shadcn-editor with improved toolbar and formatting options
- Image uploads now use server-side storage instead of base64 encoding

### Fixed

- WebSocket reconnection storm when token expires (now uses exponential backoff and auto-logout)
- Mentions and emoji picker dropdowns appearing at bottom of editor instead of near cursor

## [0.7.3] - 2026-01-12

### Added

- Rate limiting on all API endpoints (100 requests/minute default)
- Aggressive rate limiting on sensitive auth endpoints (5 requests/15 minutes)
- Rate limiting on OIDC endpoints (login: 20/minute, callback: 5/15 minutes)
- `BEHIND_PROXY` setting to safely trust X-Forwarded-For headers behind reverse proxies

## [0.7.2] - 2026-01-12

### Added

- Version dialog shows last 5 versions with scrolling
- "View all changes" button linking to GitHub CHANGELOG.md
- Changelog endpoint limit parameter (max 10 versions)

### Fixed

- Dialog scrolling with proper flex layout and 80vh height

## [0.7.1] - 2026-01-12

### Fixed

- Changelog not displaying in Docker deployments
- Changelog file now correctly copied into Docker image
- Fixed path resolution for changelog endpoint in Docker environment

## [0.7.0] - 2026-01-12

### Added

- Multiselect filters for task pages
- Users can now select multiple assignees, statuses, priorities, guilds, and initiatives simultaneously
- "Select all" and "Clear all" options in filter dropdowns
- Dropdown shows selected count (e.g., "3 selected")
- Backend now supports array parameters for all task filters using OR logic
- Changelog display in update dialog when new version is available
- Version dialog showing current version, latest version, and full changelog

### Changed

- Default My Tasks status filter now shows backlog, todo, and in_progress (excludes done by default)
- Task filtering moved to server-side for better performance
- Filters use OR logic within each filter type, AND logic between filter types
- Version number interaction changed from hovercard to dialog for both desktop and mobile
- Version dialog now displays full changelog for current version with parsed sections

### Fixed

- Task filters now correctly apply on backend instead of returning all tasks
- TypeScript type error in task query params

## [0.6.4] - 2026-01-11

### Added

- Template selection dropdown for document creation
- "Save as template" toggle when creating documents

### Fixed

- Project documents section now updates properly after attaching/detaching documents
- Cache invalidation issue causing stale document lists

## [0.6.3] - 2026-01-10

### Added

- Initiative collapsed state persistence to localStorage
- Single localStorage key for all initiative states to reduce clutter

### Changed

- Frontend now served by FastAPI instead of nginx for simpler deployment

### Fixed

- TaskAssigneeList component to work with correct TaskAssignee type
- My Tasks page crash from non-array query data

## [0.6.2] - 2026-01-09

### Changed

- Optimized task list endpoints to reduce payload size
- Moved task filtering to backend for better performance

### Fixed

- Backend test suite - 136/142 tests passing (95.8%)
- Task endpoint validation issues
- Test schema mismatches

## [0.6.1] - 2026-01-08

### Fixed

- Double scrollbar issue on ProjectTabsBar
- Improved scrolling aesthetics on Chromium browsers

## [0.6.0] - 2026-01-07

### Added

- User statistics page with metrics and visualizations
- Chart components for data visualization
- Activity tracking and reporting

## [0.5.3] - 2026-01-06

### Fixed

- PWA manifest for Chrome install prompt
- ScrollArea component on tabs bar for better UX

### Added

- Automated release CI workflow

---

## Version Format

Version numbers follow semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes, incompatible API changes
- **MINOR**: New features, backward-compatible additions
- **PATCH**: Bug fixes, backward-compatible fixes

## Categories

- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be-removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security fixes
