# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Self-deactivation / deletion UX.** Settings → Danger Zone now exposes **Deactivate Account** and **Delete Account** as two separate buttons next to their descriptions, instead of a single ambiguous opener that landed on a radio chooser. Each button takes you straight to the eligibility check for that action, the dialog title and step descriptions match the action you picked, and the deactivate copy now spells out that you'll be removed from every guild you're in (rejoining requires a fresh invite).

### Fixed

- **Orphaned projects when leaving a guild.** Leaving a guild while owning projects in it would silently strand the rows: the user's initiative membership got dropped, no DAC permission survived, and guild admins (who have no implicit project bypass) couldn't reach them. Leaving now requires nominating a new owner per project — the leave dialog lists every project you own in the guild and a Select to pick a new owner, the eligibility endpoint surfaces the same list so the SPA can pre-flight the prompt, and the backend rejects a leave with a missing or surplus transfer map. The OIDC group-sync removal path, which has no UI to ask, auto-transfers ownership to an active initiative manager (falling back to a guild admin) before dropping the user, and logs a warning when neither exists.

## [0.43.0] - 2026-05-01

### Added

- **Spreadsheet documents.** Pick **Spreadsheet** from the document-type dropdown when creating a new document to get a virtualized cell grid that scrolls horizontally and vertically without bound. Edit cells with click + type / Enter / Tab / arrow keys; copy and paste between cells (and from Numbers / Excel / Sheets — multi-row / multi-column blocks expand into the grid). Toolbar buttons export the sheet as CSV or import a CSV file. Cells store strings, numbers, booleans, or blanks; numeric- and boolean-looking inputs get auto-coerced to the right type, and booleans render as interactive checkboxes. Edits sync in real time between users on the same document over the existing yjs collaboration infrastructure, and each user's currently-selected cell shows up to peers as a colored ring with their name.

- **Webhook subscriptions for the advanced-tool service.** Outbound HMAC-signed event delivery (sha256 over `timestamp + "." + body`) so the embed can react to writes (e.g. `task.created`) without polling. Subscriptions are guild-scoped, RLS-protected, and the HMAC secret is returned only at create time. _Note: likely temporary scaffolding for testing the embed integration; expect the contract to shift as it shakes out._

- **Delegation auth for the advanced-tool service.** Accept short-lived RS256-signed JWTs from the embed's backend so it can call Initiative on a user's behalf. Existing RLS + role-permission checks still gate every action — delegation answers only "who is acting." Deactivated users can't be impersonated. Disabled by default; opt in with `AUTO_DELEGATION_PUBLIC_KEY_PEM`.

- **Embedded advanced tool integration.** Initiative now supports plugging in an externally-deployed companion app as an iframe panel under specific initiatives or as a dedicated guild settings tab. Operators set `ADVANCED_TOOL_NAME` and `ADVANCED_TOOL_URL` on the backend; without those, the entire feature stays fully hidden — no UI surface, no per-initiative toggle, and the API endpoints return 404.
  - **Per-initiative panel** — initiative managers turn it on under Initiative settings → Details → Advanced Tools. Once enabled, the panel becomes the first item in the initiative's sidebar group for any user whose role grants the new `advanced_tool_enabled` permission.
  - **Per-guild panel** — guild admins get a dedicated tab in guild settings for cross-initiative or admin-only views. The tab only appears when the deployment has an advanced tool URL configured AND the user is a guild admin.
  - **Role-based access control** — two new initiative-level permission keys (`advanced_tool_enabled`, `create_advanced_tool`) gate visibility and creation rights at the role level. Built-in managers get both by default; members get neither.
  - **Security model** — embedding uses a 60-second audience-scoped JWT delivered to the iframe via postMessage (never the URL). Strict origin checks on every postMessage; iframe is sandboxed (`allow-scripts allow-same-origin allow-forms allow-downloads`); locale forwarded so the embed picks up the user's language without re-prompting. JWT can be signed with RS256 via `HANDOFF_SIGNING_PRIVATE_KEY_PEM` so the embed verifies with a public key only — no shared secret. Falls back to HS256 with `SECRET_KEY` for OSS deployments. Tokens carry a `jti` so the embed can refuse repeat redemption within the validity window. The handoff endpoint authorizes membership + role + master-switch + URL-configured before issuing a token, so the embed never has to make access decisions on its own.
  - **Runtime config endpoint** — `GET /api/v1/config` exposes the deployment's advanced-tool config (URL + name) so the SPA discovers it at boot without rebuilding the bundle.

- **Project export & import.** Settings → Advanced now offers an **Export as JSON** button that downloads a self-contained JSON file with the project's metadata, task statuses, project tags, tasks (with subtasks, recurrence, priorities, dates, and custom property values), and the property *definitions* those tasks reference. From the projects page, an **Import** button next to **New project** accepts a JSON export and recreates the project under any initiative you can create projects in — including across separate Initiative installations. References are name- and email-based so IDs from one database don't leak into another:
  - **Tags** are matched against the target guild by name; new tags are created if they don't exist.
  - **Task statuses** are recreated per-project from the export.
  - **Custom properties** are matched by name in the target initiative. If the target already has a property with the same name but a different type, the imported one is renamed `<name>_<type>` (e.g. `Severity_select`) so the existing property is never mutated.
  - **Assignees** are matched by email against the target initiative's members. Unmatched emails are reported in a toast warning and silently dropped — the importer becomes the project owner and `created_by` for every task.
  - The format is **versioned** (`schema_version`) so future format changes can refuse stale exports cleanly.

- **Trash and Restore.** Deleting a project, task, document, comment, initiative, tag, queue, queue item, or calendar event now sends it to a trash can instead of permanently destroying it. Items stay there for the guild's retention period (default 90 days; admins can change it under **Settings → Guild → Trash retention** or set "Never" to keep things forever).
  - **Personal view** — every member sees a **Trash** tab under their profile listing the things they deleted, with a **Restore** button next to each.
  - **Guild view** — guild admins also get a **Trash** tab under **Settings → Trash** that shows everything trashed in the guild plus an admin-only **Delete now** button for permanently purging an item before its retention timer is up.
  - **Restore handles missing owners** — if you trashed a task and the owner has since left the initiative, restore opens a picker so you can hand ownership to someone else before bringing the row back.
  - **Cascades preserved** — trashing a project hides its tasks too; restoring it brings them back together. The trash listing only shows the parent so you don't get drowned in 200 cascaded rows.
  - **Auto-purge** runs hourly so expired items leave on their own.
  - The Postgres layer now refuses raw `DELETE` from the application role on every soft-delete-capable table, so a stray query can't accidentally bypass the trash flow.

- Export users as CSV from **Settings → Users** (guild admins) and **Settings → Admin → Users** (platform admins). Each row gets an **Export** button, and the card header has **Export all as CSV**. Exports include ID, email, full name, role, status, and initiative roles — enough for HR or compliance teams to keep an offline record before an account is removed.

- **Chester the Mimic** — a pixel-art treasure chest mascot now greets you in toast notifications. Each toast type pairs with a Chester mood (success → proud sparkles, error → chomping, warning → thinking, info → talking, default → idle), and the seven mood SVGs ship as standalone animated assets. Platform admins can preview them all from the new "Chester toast playground" card in **Settings → Admin → Branding**.

- **Keep screen awake.** A new toggle under **Settings → Interface** prevents this device's screen from dimming or locking while the app is open. Useful for long planning or reading sessions on a tablet at the table. The setting is per-device — it's saved locally (localStorage on web, Capacitor Preferences on native) and never synced to the backend, so each device can opt in independently. Uses the Screen Wake Lock API on web and the native idle-timer/`FLAG_KEEP_SCREEN_ON` flag on Capacitor builds.

### Changed

- **Account deletion now has three options instead of one.**
  - **Deactivate** (new) — your account is locked but kept intact. An admin can reactivate it later. Pick this if you might come back.
  - **Delete my account** (replaces the previous "soft delete") — your name, email, avatar, and login are wiped. The account row stays so the comments, tasks, and documents you authored remain visible (attributed to "Deleted user #{id}") instead of vanishing from your team's history. This is permanent.
  - **Hard delete** (admin only) — completely removes the row and everything attributed to it. Hidden from the user-facing dialog; only platform admins can do this from the admin page.

  All account-deletion paths now require you to transfer ownership of any projects you manage before submitting, so projects always have an active owner.

- The platform users page status column shows **Active**, **Deactivated**, or **Anonymized** in place of the old Active/Inactive label, and the "Reactivate" button is hidden for anonymized accounts (their data is gone — there's nothing to bring back).

- Anywhere a deleted user used to appear (comment authors, task assignees, mentions, calendar attendees, document collaborators), they now show as **Deleted user #{id}** with a neutral avatar instead of a stale name or email.

- Anonymized users are filtered out of "add member" and @-mention pickers, so you can't accidentally assign or mention someone whose account no longer exists.

- **Single Docker image for OSS and hosted deployments.** The dual-build setup (separate `*-infra` image with `INSTALL_INFRA_EXTRAS=true`) is gone — one image now serves every deployment, with the advanced tool integration enabled at runtime via env vars instead of at build time. The `INSTALL_INFRA_EXTRAS` build arg, the `requirements-infra.txt` extras file, and the `build-docker-infra` GitHub Actions job have been removed. Self-hosters get the same image we run; auditors can verify by inspection that the public image has no automation/event-publishing code paths.

- Bump lexical dependencies for a more stable document editor.

- Migrated the document editor to Lexical 0.44's Extension API. No user-visible behavior change, but the editor now uses `LexicalExtensionComposer` with `defineExtension` instead of the legacy `LexicalComposer` + plugin-list pattern, which clears the deprecation warning around `CodeNode` and aligns the editor with the upstream shadcn-editor architecture so future Lexical updates are easier to absorb.

### Fixed

- Read-only members can now create new documents from a template they have access to. Previously the copy required write access to the template, which defeated the point of templates being shared starters. Copying a non-template document still requires write access on the source.

- Deleting a document from the document settings page no longer fires two success toasts.

- Drag-scrolling a kanban board no longer smears a text selection across every card the pointer passes over.

- The document markdown converter now round-trips paragraph structure correctly. Toggling **Convert from markdown** previously turned a `\n\n` paragraph break into two stacked soft line breaks; converting back then re-emitted single newlines, so paragraphs steadily collapsed each time you toggled. Paragraph breaks now serialize as `\n\n` in markdown and parse back as real paragraphs, and shift+return soft breaks survive the round trip via the standard CommonMark hard-break syntax.

- The guild filter on **My Tasks** and **Created Tasks** silently ignored your selection — picking one or more guilds still showed tasks from every guild you belong to. The pages now narrow correctly.

- Documents owned by a departing user no longer become orphaned when the user leaves the initiative — whether they leave the guild, deactivate or delete their own account, get removed by an admin, or get unassigned via OIDC sync. The initiative's project managers automatically inherit ownership of those documents, so anyone who needs to find or clean up old work after a team move still can.

- Custom properties UI is now translated to Spanish and French. Previously, users on those locales saw English labels throughout the properties picker, manager, and filters.

### Removed

- **Automation engine, event publisher, and `aioboto3` dependency.** Domain-event fan-out for automation now lives entirely in the separately-deployed advanced tool service rather than in the FOSS backend. The bundled Kinesis publisher, the in-process automation engine, the Redis dependency, and the `automations_enabled` initiative flag (replaced by the generic `advanced_tool_enabled` slot) are all gone from the FOSS image. Fresh installs are unaffected; existing databases get a clean migration path.

## [0.42.1] - 2026-04-28

### Fixed

- The task edit page sometimes opened with the wrong status, priority, and recurrence shown until you nudged the page (added a tag, changed a property, etc.), then it would suddenly snap to the right values. All three fields now read from the task's own data on the first render instead of waiting for a delayed copy into local form state, so the form is correct the moment the task loads.

## [0.42.0] - 2026-04-23

### Added

- **Custom properties** on documents, tasks, and calendar events. Initiative managers define reusable properties from a new Custom Properties tab in initiative settings, picking from nine types (text, number, checkbox, date, date & time, URL, single-select, multi-select, or person). Attach them to any document, task, or event alongside tags; filter by them in every list; toggle per-property columns on the task and document tables; and see compact chips on kanban cards, document cards, and the calendar list view. Select/multi-select pickers support creating new options inline without leaving the entity.

### Removed

- Moving a project between initiatives. The "Initiative ownership" card is gone from project settings and `PATCH /projects/{id}` no longer accepts `initiative_id`. The move crossed a privacy boundary — the project and everything attached to it suddenly became visible to a different initiative's members — and each new initiative-scoped attachment (role permissions, tags, custom properties, calendar events) needed its own cascade rule to stay coherent. The cost of keeping the move correct grew faster than the demand for the feature. Create the project in the right initiative from the start; if you end up in the wrong one, duplicate it into the target and delete the original. A follow up will enable export and import for projects that will cover this use case.

### Changed

- Avatars are now consistent everywhere a person appears. The same deterministic color that powers the whiteboard cursor and Lexical editor caret tints the initials fallback in comments, task assignees, queue item owners, @-mention typeahead, calendar attendees, custom-property people pickers, and the collaboration badge. The collaboration badge and custom-property people cells also show uploaded profile pictures when available; previously both only ever showed initials. Non-user avatars like guild icons are unchanged.

## [0.41.0] - 2026-04-21

### Added

- New **smart link** document type. Create one from the dialog's new third tab by pasting a URL — Figma files, YouTube videos, Loom recordings, Vimeo videos, Google Docs/Sheets/Slides/Drawings, Miro boards, Airtable embed views, and Office docs are embedded inline; other URLs render a link card that opens in a new tab. Only the URL is stored; Initiative doesn't fetch anything from the link. Adding support for a new provider later automatically upgrades any existing smart-link docs whose URLs match that provider — no migration needed, since the provider is always derived from the URL at render time.
- Multiplayer cursors on whiteboards. When multiple users edit the same whiteboard document at once, each person now sees the others' pointer positions in real time, labeled with their name and tinted with their avatar color. Cursor updates piggyback on the existing Yjs awareness channel, so no new backend routes were needed.

### Changed

- Collaboration cursor colors are now deterministic per user and consistent across the app. The Lexical document editor caret, whiteboard cursor, and collaboration badge avatar all derive the same color from the user's id, so a given user shows up the same way everywhere. Previously the Lexical caret picked a random color per session and the avatar badge used a separate palette, so none of them agreed.

## [0.40.0] - 2026-04-20

### Added

- Optional Task Completion Visual Feedback effect when you mark a task you're assigned to as Done. Choose from None (default), Confetti, +1 Heart, Natural 20 d20 roll, Gold Coins, or Random (surprise me) under user settings → Interface. All effects use a unified 8-bit pixel-art aesthetic.
- Sound and haptic siblings to the task completion feedback. The new "Sound on task completion" and "Vibration on task completion" toggles in user settings → Interface play a short pop and trigger a two-pulse vibration (where supported) when you mark **any** task done — not just one assigned to you, since these are subtle enough to fire on every closeout. Both default to on; existing users get them enabled automatically. Haptics use the Capacitor Haptics plugin on native iOS/Android and fall back to the Web Vibration API in browsers that support it.

## [0.39.1] - 2026-04-18

### Added

- Fullscreen toggle in the document and whiteboard editors. The editor, its toolbars, action bar, and collaboration status take over the window for distraction-free writing or large-canvas diagramming. The Fullscreen button sits inline with the collaboration status badge above the editor.

### Fixed

- "Not tagged" filter in the Documents page tag tree view now actually filters to untagged documents. The page was computing the selection state but never sending the `untagged` query parameter to the backend, so selecting "Not tagged" returned every document instead of only the untagged ones.
- Leaving a collaborative document now tears the connection down cleanly. Other collaborators no longer see the leaver's avatar flicker (disappear briefly then reappear), and the "Collaboration connection failed — Maximum reconnection attempts reached" toast no longer fires after the user has navigated away from the document. The unmount cleanup in `useCollaboration` was using a soft, debounced `disconnect()` (a React Strict Mode optimization) instead of `destroy()`, leaving the provider alive in the global pool, the reconnect loop running, and the error callback still wired to the unmounted page's toast.

## [0.39.0] - 2026-04-14

### Added

- Improved task status UX: each status now has a customizable color and icon, with smart defaults driven by its category (backlog, todo, in progress, done). Kanban column headers show the status icon and a colored accent bar, and every status dropdown (kanban, project table/gantt rows, My Tasks, tag task lists, task edit page) now shows the icon beside the name and mirrors the active status color on the trigger border.

### Fixed

- Auto-redirect to the welcome/login page when the access token expires, instead of leaving the app in a broken state until the user manually refreshes. Shows a "Your session has expired" toast before the redirect.
  - Backend now returns `401 Unauthorized` (with `WWW-Authenticate`) for expired or invalid JWTs, invalid device tokens, and malformed token payloads, rather than `403 Forbidden`. Genuine authorization failures are unchanged.
  - Frontend 401 interceptor no longer silently swallows expired-session 401s on web cookie auth: an explicit session flag tracks whether a user is currently signed in, regardless of whether the in-memory bearer token was ever populated.
- Fix manual logout so previously-issued JWTs are actually invalidated server-side. The logout endpoint was using `AdminSessionDep` while `get_current_user_optional` used `SessionDep`, so in production the `current_user` object came from a detached session and the `token_version += 1` bump was silently dropped on commit. Previously-signed JWTs (and any still-cached HttpOnly cookie) stayed valid until natural expiry, letting users navigate back into protected pages by typing the URL after clicking "Sign out". The endpoint now uses a single `SessionDep` so FastAPI's per-request dependency cache hands both sites the same session, and the commit actually persists.

## [0.38.1] - 2026-04-12

### Fixed

- Fix whiteboard persistence losing edits on refresh / navigation
  - Add localStorage write-ahead cache so unsaved scenes survive page unload regardless of keepalive PATCH timing
  - Gate WhiteboardDocumentEditor on scene-ready state so Excalidraw's `initialData` captures the correct scene instead of the empty `useState` default
  - Skip stale Yjs initial sync in observer — only apply live updates from other users after bootstrap
  - Only clear `yjs_state` on PATCH when no active collaborators are in the room, preventing a data-loss window during periodic content-sync
  - Guard the document load effect so PATCH responses don't reset the live whiteboard scene mid-edit
- Fix whiteboard cache poisoning when rejoining a live room — a user rejoining with a stale local cache no longer clobbers the live room's state. The bootstrap now applies the Y.Map state whenever other collaborators are present, and local edits are gated behind the bootstrap decision so Excalidraw's initial mount `onChange` can't broadcast the cached scene.
- Whiteboards in collaboration mode now sync to `document.content` every 2s instead of 10s, matching the non-collab debounce. Narrows the stale-content window for non-collab readers and reduces the `yjs_state` / `content` desync window.

## [0.38.0] - 2026-04-10

### Added

- New `whiteboard` document type backed by Excalidraw
  - Create whiteboards via a new "Document type" dropdown on the Create Document dialog
  - Lazy-loaded canvas with full Excalidraw toolset (shapes, freehand, arrows, text, images)
  - Live collaboration via the existing Yjs WebSocket — whiteboard scene is mirrored to a single-key Y.Map and persisted alongside text documents
  - Theme syncs with the app's light/dark mode
  - Reuses the existing permissions, tags, comments, templates, and project-attachment infrastructure
  - Templates are filtered by document type so users don't accidentally copy a Lexical template into a whiteboard slot

### Fixed

- `normalize_document_content` is now type-aware so non-Lexical document content (whiteboard scenes, file metadata) isn't silently mutated to inject a Lexical `root` paragraph on save

## [0.37.0] - 2026-04-09

### Added

- Offline mode for the document editor
  - Persistent mode-aware toast when the device loses network connectivity
  - New "Offline" state in the collaboration status badge (now also shown in non-collaborative mode)
  - Autosave is skipped while offline and automatically retries on reconnect, so edits aren't lost
  - Uses `@capacitor/network` for accurate status on native, `navigator.onLine` on web

### Changed

- **React 18.3 → 19.2.** Bumped `react`, `react-dom`, `@types/react`, and `@types/react-dom` to 19.x. Required widening a drag-scroll hook's ref type to accept the new nullable `RefObject<T | null>`, importing `JSX` from `react` in a legacy Lexical `EmbedNode` (React 19 removed the global `JSX` namespace), and deleting two unused editor shim files that imported the now-removed `react-dom/test-utils`. All major peer deps (Lexical, Radix, TanStack Query/Router, cmdk, sonner, Testing Library 16) already declared `^19` support.
- **react-i18next 16 → 17** and **i18next 25 → 26.** Major bumps; react-i18next 17 requires i18next ≥ 26. None of i18next 26's breaking changes (`initImmediate`, legacy monolithic `format` function, `showSupportNotice`, `simplifyPluralSuffix`) are used in our config.
- Bumped `sqlmodel` 0.0.37 → 0.0.38 (backend ORM).
- Bumped `vite` 7.3.1 → 7.3.2, `msw` 2.12.14 → 2.13.0, `i18next-http-backend` 3.0.2 → 3.0.4, `@types/node` 25.5.0 → 25.5.2, `email-validator` 2.1.1 → 2.3.0, `python-multipart` 0.0.22 → 0.0.24.

### Fixed

- Document edits saved in non-collaborative mode are no longer overwritten by a stale `yjs_state` when re-enabling live collaboration. The document update endpoint now clears `yjs_state` and invalidates any empty in-memory collaboration room whenever content is written via the REST PATCH.

## [0.36.2] - 2026-04-08

### Added

- Table action menu in the document editor — click the chevron in any table cell to insert/delete rows and columns, toggle header rows/columns, or delete the table

### Fixed

- Fix tables shrinking from full width after deleting a column (changed table CSS from `w-fit` to `w-full`)
- Fix empty table rows/columns being removed during markdown round-trip (divider regex matched empty cells as header separators)

## [0.36.1] - 2026-04-06

### Added

- Global "Add Task" wizard dialog accessible from My Tasks, Tasks I Created, and the Command Center (Ctrl+K)
  - Multi-step flow: select guild → initiative → project → opens task composer on that project
  - Remembers last-used project for quick repeat task creation
  - Auto-skips steps when only one option exists (single guild or initiative)
  - Only shows projects the user has write access to

### Fixed

- Replace `imghdr` module with magic-bytes detection for Python 3.13 compatibility
- Fix double bottom inset on Android when the keyboard is visible (Capacitor SystemBars and safe-area plugin both applying insets)
- Remove `EdgeToEdge.enable()` to prevent conflict with safe-area plugin's inset management

## [0.36.0] - 2026-04-04

### Added

- Automations initiative tool (infra/paid feature, disabled by default)
  - Dual-layer feature gating: `ENABLE_AUTOMATIONS` env var (infrastructure) + per-initiative `automations_enabled` toggle
  - `automations_enabled` and `create_automations` permission keys with role-based access control
  - Stub `GET /automations` API endpoint for future pipeline integration
  - `GET /settings/automations-config` public endpoint for runtime feature discovery
  - Sidebar link with Zap icon, initiative settings toggle, and placeholder page
  - Build-time `VITE_ENABLE_AUTOMATIONS` flag for complete frontend tree-shaking in public builds
- Visual automation flow editor (n8n / Home Assistant style)
  - Drag-and-drop canvas powered by `@xyflow/react` with pan, zoom, and minimap
  - 5 node types: Trigger, Action, Condition (if/else branch), Delay, Loop (for-each)
  - Animated bezier edges with delete-on-hover
  - Node palette sidebar for dragging new nodes onto the canvas
  - Property inspector panel (Sheet) with type-specific forms
  - Automations list view with create/delete and card grid
  - 7 action types: send webhook, update task, send notification, add/remove tag, move to project, archive task
- Automation flow CRUD API with graph validation (DAG check, single trigger enforcement)
  - Full flow persistence to database (replaces localStorage)
  - Run history endpoints for execution logs
  - Frontend migrated to React Query hooks backed by backend API
- `POST /notifications/send` endpoint for engine-driven push notifications
- Redis service added to docker-compose (commented, for infra deployments)
- Automation engine backend infrastructure
  - Database tables: `automation_flows`, `automation_runs`, `automation_run_steps` with full RLS
  - `automation_engine` PostgreSQL role with BYPASSRLS for direct engine writes
  - Redis Streams event publisher for domain events (`task_created`, `task_updated`)
  - Service token authentication (`AUTOMATION_SERVICE_TOKEN`) for engine API callbacks
  - `REDIS_URL` config setting for event bus connectivity
- Dual Docker image CI/CD: publishes both `initiative` (public) and `initiative-infra` (paid) images
- Vite config now loads `.env` files from `backend/` directory for shared env vars
- Added Ctrl+S / Cmd+S keyboard shortcut to save in the document editor

### Fixed

- Cross-guild task/event links in My Calendar and My Tasks calendar view now navigate to the correct guild instead of the active guild

### Changed

- Bumped Lexical editor from 0.41 to 0.42 (all packages unified)
- Bumped asyncpg from 0.29.0 to 0.31.0
- Bumped httpx from 0.27.0 to 0.28.1
- Bumped SQLModel from 0.0.24 to 0.0.37
- Bumped pycrdt from 0.12.46 to 0.12.50
- Bumped PyJWT from 2.11.0 to 2.12.0
- Updated Orval to 8.6.2

### Removed

- Removed unused dependencies: `radix-ui` (unified), `@tanstack/router-devtools`, `autoprefixer`, `postcss`, `@tailwindcss/postcss`, `lodash`, `@types/lodash`
- Deleted unused `postcss.config.js`

## [0.35.0] - 2026-03-26

### Added

- Calendar events feature with Google Calendar-like UI
  - Initiative-scoped events with title, description, location, date/time, color, and recurrence
  - Attendee system with RSVP (pending, accepted, declined, tentative)
  - `events_enabled` toggle and `create_events` permission key on initiatives
  - Full CRUD, attendee management, RSVP, tags, and document attachment endpoints
- Reusable multi-view CalendarView component (day, week, month, year, list)
  - Month: multi-day spanning bars for all-day events, dot+time+title for timed events
  - Week/Day: positioned cards spanning full hour range with colored sidebar
  - Year: mini-month grids with per-event color dots or count badges
  - List: date, weekday, description, stacked attendee avatars with tooltip, time range
- Calendar sidebar link under each initiative with CalendarDays icon
- Event creation via clicking calendar day slots with date/time pre-fill
- Attendee picker using initiative members with searchable combobox
- Task recurrence selector reused for event recurrence

- Calendar view toggle on My Tasks and Created Tasks pages
- My Calendar page: cross-guild unified calendar combining tasks and events
  - Filters for status category, priority, and guild (persisted to local storage)
  - Events toggle to show/hide calendar events alongside tasks
  - Global calendar events backend endpoint (`GET /api/v1/calendar-events/global`)
- Filter and sort preferences persisted to local storage on My Tasks, Tasks I Created, My Projects, and My Documents pages
- Spanish and French translations for My Calendar page
- iCal (.ics) import/export for calendar events
  - Export events as `.ics` files (per-guild and cross-guild)
  - Import events from `.ics` files with preview and initiative selection
  - RRULE recurrence mapping (best-effort bidirectional conversion)
  - Export/import buttons on guild Events page and My Calendar page
  - Spanish and French translations for import/export UI

### Changed

- Replaced ProjectCalendarView with generic CalendarView component for project tasks
- Project task calendar now shows assignee avatars in list view
- Initiative settings: Calendar toggle alongside Queues under Advanced Tools

### Fixed

- Calendar event update endpoint now validates date ordering and 24-hour limit for timed events
- Document attachment on calendar events now scoped to guild, preventing cross-guild association

## [0.34.2] - 2026-03-18

### Fixed

- PWA manifest: fixed icon paths, split `any maskable` purpose into separate entries, added desktop and mobile screenshots for richer install UI

## [0.34.1] - 2026-03-03

### Changed

- Moved search/Cmd+K button from sidebar footer to top bar for better discoverability
- Aligned sidebar header, top bar, and activity sidebar header heights

### Fixed

- Lighthouse accessibility: added aria-labels to home link, progress bars, task status select, page size select, and searchable combobox
- Lighthouse SEO: added meta description and robots.txt
- Lighthouse performance: deferred Google Fonts loading, added Cache-Control headers for hashed static assets

## [0.34.0] - 2026-03-01

### Added

- French (Français) locale — full translation of all 19 frontend namespaces and backend email templates
- Image and Markdown file uploads for documents — images display with lightbox zoom, markdown files render with source/rendered toggle
- Heading anchor links (`#slug`) in both markdown file viewer and native Lexical editor — clicking scrolls to the matching heading

### Fixed

- `app_admin` role missing grants on `uploads` table — caused `permission denied` errors when serving uploaded files
- Markdown file upload rejected with 400 error when `python-magic` returns variant MIME type (e.g. `text/x-markdown`)

## [0.33.2] - 2026-02-28

### Added

- Column header sorting on the My Projects page (name and updated columns) with server-side sort support

## [0.33.1] - 2026-02-27

### Security

- Docker container now runs as non-root user (`app`, UID/GID 1000 by default) instead of root — compatible with rootless Docker and Podman. Set `PUID`/`PGID` environment variables to customize (e.g. `PUID=99 PGID=100` for Unraid's `nobody:users`)

### Fixed

- `app_admin` role missing grants on queue tables — caused `permission denied for table queues` errors for background jobs and seed scripts
- Added `ALTER DEFAULT PRIVILEGES` for `app_admin` so future migrations automatically inherit grants (previously only `app_user` had default privileges)

### Upgrade Notes

- **Uploads volume ownership**: The container now runs as a non-root user (UID 1000 by default). If file uploads fail after upgrading, fix ownership on the host: `chown -R 1000:1000 ./uploads`. Alternatively, set `PUID` and `PGID` to match your host user (e.g. `PUID=99 PGID=100` for Unraid)

## [0.33.0] - 2026-02-27

### Added

- Queue feature: turn/priority tracking with turn controls (start, stop, advance, previous, reset), per-item user/document/task linking, and tag support
- Queue DAC (Discretionary Access Control): user-level and role-based permissions with read/write/owner levels
- Queue settings page with details editing, role/user permission management, and delete
- Queue user permissions table: filtering by name, multiselect with bulk access change/remove, pagination, and "Add All" button
- Queue backend integration tests (19 tests covering CRUD, items, turns, DAC, and associations)
- Queue frontend and backend test factories
- Initiative-level feature flags: per-initiative toggle to enable/disable advanced tools like Queues; Advanced Tools accordion in create and settings dialogs
- Queues tab on initiative detail page when queues are enabled
- Queue list filter bar with search, active/inactive status filter, and initiative filter

### Changed

- Roles tab redesigned from data table to card-per-role layout with grouped permission switches and an Advanced Tools accordion, scaling to any number of permissions without horizontal scrolling
- Removed standalone "All Queues" sidebar link; queues are now accessed per-initiative

## [0.32.4] - 2026-02-26

### Security

- HTML and HTM files served via `/uploads/*` now force `Content-Disposition: attachment` and `Content-Security-Policy: script-src 'none'`, preventing stored XSS via uploaded HTML documents (GHSA-v38c-x27x-p584, reported by G3XAR).
- JWT tokens are now invalidated on logout and password change via server-side token versioning, preventing continued access with a captured token (GHSA-hww6-3fww-xw3h, reported by G3XAR). All active sessions will be signed out on first deployment of this update.

## [0.32.3] - 2026-02-26

### Added

- Dark Knight color theme: AMOLED true-black dark mode with dark maroon and bat-signal yellow accents
- ORC color theme: earthy green theme with vivid orc-skin green accents and cave/swamp dark mode
- Aboleth color theme: Monokai-inspired dark lair with vivid bioluminescent accent colors (lime, cyan, purple, orange, hot pink)
- Unicorn color theme: Bold and bright rainbow colors

## [0.32.2] - 2026-02-25

### Security

- Sensitive database fields are now encrypted at rest using Fernet (AES-128-CBC): AI API keys at platform, guild, and user levels; OIDC client secret; SMTP password. Existing data is migrated automatically via Alembic. The encryption key is derived from `SECRET_KEY`.
- User email addresses are now encrypted at rest. The `users` table stores an HMAC-SHA256 hash (`email_hash`) for fast indexed lookups and a Fernet ciphertext (`email_encrypted`) for display/sending; the plaintext `email` column is removed. Guild invite email addresses are also encrypted. Existing data is migrated automatically.
- Uploaded files now require authentication to access; the `/uploads/*` path no longer serves files to unauthenticated users. The backend validates the user's token from the `Authorization` header (reported by Adem Kucuk).
- Uploaded files are now restricted to members of the guild they were uploaded in. The backend tracks file→guild ownership in a new `uploads` table and returns 403 to authenticated users who are not members of the owning guild. Covers image attachments, document file uploads (PDF, DOCX, etc.), and files created by duplicate/copy/template operations. Pre-existing files without a database record remain accessible to any authenticated user for backwards compatibility.
- File-type documents (PDFs, DOCX, etc.) now enforce document-level read permission on download. A new `GET /api/v1/documents/{id}/download` endpoint replaces direct `/uploads/*` access for file documents; guild membership alone is no longer sufficient — the requester must have explicit read, write, or owner permission on the document. Inline viewing (`?inline=1`) and attachment download use the same permission check.
- Web sessions now use HttpOnly `SameSite=Lax` cookies instead of `localStorage` for JWT storage, eliminating XSS token theft risk and removing the JWT from browser history/server logs. The cookie is sent automatically for all requests including media (`<img>`, `<iframe>`); native (Capacitor) is unchanged and continues to use DeviceToken headers stored in Capacitor Preferences.
- Replaced `python-jose` with `PyJWT` for JWT handling. `python-jose` (through 3.3.0) has an algorithm confusion vulnerability with OpenSSH ECDSA keys and other key formats (similar to CVE-2022-29217) and is no longer maintained.
- Rate limiting added to `/uploads/*` (600 req/min) and `GET /documents/{id}/download` (30 req/min); file download access is now logged.
- Upgraded `python-multipart` from 0.0.9 to 0.0.22, fixing a DoS via malformed `multipart/form-data` boundary and an arbitrary file write via non-default configuration.
- Added Dependabot configuration (`.github/dependabot.yml`) for automated dependency update PRs on backend, frontend, and GitHub Actions.

### Changed

- Command Center search placeholder now reads "Search in \<guild name\>" instead of a generic string

## [0.32.1] - 2026-02-23

### Fixed

- My Tasks date groups (Overdue, Today, This Week, etc.) now respect the user's timezone — backend uses `AT TIME ZONE` with a `tz` query parameter instead of UTC `now()`
- `useAllDocumentIds` cache corruption after visiting the Initiatives page — fixed React Query key collision with `useDocumentsList`

### Changed

- Command Center shows project emoji icons and file-type-specific document icons (PDF, Word, Excel, PowerPoint) with color coding
- Extract shared `getDocumentIcon` / `getDocumentIconColor` helpers in `fileUtils.ts` — used by both Command Center and DocumentCard

## [0.32.0] - 2026-02-23

### Added

- Command Center (`⌘K` / `Ctrl+K`) for quick navigation to projects, tasks, documents, and pages with fuzzy search — accessible via sidebar shortcut badge or 3-finger tap on mobile
- Reusable `StatusMessage` component for consistent error states across detail pages
- Distinct 404/403 error messages on Project, Document, Tag, and Initiative detail pages using `Empty` card layout with contextual icons
- "Guild not available" page when navigating to a guild the user isn't a member of (replaces silent redirect)
- Rate-limit error message ("Too many requests") instead of misleading "Check your credentials" on login/register
- Row virtualization for DataTable using `@tanstack/react-virtual` — only visible rows exist in the DOM, tested with 10k tasks
- Virtualized Gantt view with sticky day headers and pinned task name column
- Virtualized Kanban columns (activates above 20 tasks per column) with memoized card components and DnD compatibility
- Collapse all / expand all buttons for sidebar initiative list and tag browser
- Memoized virtual cell rendering to prevent expensive re-renders during scroll

### Fixed

- Navigating to an inaccessible guild no longer poisons the active guild state, which previously caused "Unable to load" errors on the home page after redirect
- Dashboard "Recent Comments" no longer leaks comments from projects/documents the user lacks access to — filters by DAC permissions (direct + role-based)

### Security

- Add initiative-scoped RESTRICTIVE RLS policies to `tasks`, `task_statuses`, `subtasks`, and `task_assignees` — previously only had guild-level isolation

### Changed

- Vendored editor color picker (~1,800 lines) — replaced with existing shadcn-io color picker + Popover in font color and background color toolbar plugins
- Lazy-load editor color picker content so the `color` npm package is only fetched when a user opens the font/background color popover
- Lazy-load 4 profile settings pages (profile, notifications, interface, danger zone) — reduces index bundle by ~75 kB
- Replace pointless `React.lazy()` with static imports for `LexicalTypeaheadMenuPlugin` and `emoji-list` — both were already pinned to the editor chunk by co-located static imports, eliminating Vite "dynamically and statically imported" warnings
- Sidebar collapsed sections (initiatives, tags) no longer mount child DOM nodes — lazy-render on expand
- Skip `useSortable` hooks when drag-and-drop is disabled (sorting/grouping active) for better scroll performance
- Keep previous React Query data as placeholder for snappier page navigation
- - Replaced `sort_by`/`sort_dir` string parameters on the tasks list endpoint with a structured `sorting` JSON parameter (`SortField[]`) — enables multi-column sorting (e.g. date group then due date) using the same pattern as `conditions` uses `FilterCondition[]`
- Frontend task tables (`useGlobalTasksTable`, `TagTasksTable`, dashboard, route loaders) now pass `SortField[]` arrays instead of individual sort strings

## [0.31.5] - 2026-02-20

### Fixed

- `OIDC_ENABLED` env var no longer prevents admins from disabling OIDC via the UI — env var now only seeds on first boot instead of overriding the DB value on every read
- Guild switching no longer shows stale sidebar data — restored query cache invalidation on guild switch that was accidentally removed during React Query migration
- HTML `<strong>` tags rendered as literal text in delete confirmation dialogs — switched to react-i18next `Trans` component for proper bold rendering in initiative, guild, and settings dialogs (en + es locales)
- Defensive `Array.isArray` guard in document template queries to prevent crash on non-array data
- Admin initiative member role promotion (500 error) — endpoint referenced non-existent `.role` attribute on `InitiativeMember`; fixed to resolve roles via `role_id` FK
- Admin delete user dialog 404s when fetching initiative members across guilds — added admin endpoint `GET /admin/initiatives/{id}/members` that bypasses RLS
- Self-deletion dialog 404s when fetching initiative members across guilds — added user endpoint `GET /users/me/initiative-members/{id}` that bypasses RLS for owned initiatives

### Changed

- Centralized settings and AI settings mutation hooks (Phase 4a) — 13 new hooks in `useSettings.ts` and `useAISettings.ts` replace inline mutations across 7 settings pages/components; added `MutationOpts` to `useUpdateRoleLabels`
- Centralized remaining mutation hooks (Phase 4b) — 22 new hooks across `useAdmin.ts`, `useUsers.ts`, `useSecurity.ts`, and new `useImports.ts`; added `MutationOpts` to 11 existing hooks in `useComments.ts`, `useTags.ts`, `useNotifications.ts`; no `.tsx` file imports `useMutation` directly
- Centralized inline `useMutation` hooks for tasks, subtasks, task statuses, project members, role permissions, and project documents into domain hook files (`useTasks.ts`, `useProjects.ts`) — replaces ~50 inline mutations across 15 component/page files
- Consolidated standalone `useProjectFavoriteMutation` and `useProjectPinMutation` hooks into `useProjects.ts` as `useToggleProjectFavorite` and `useToggleProjectPin`
- All mutation hooks now accept an optional `MutationOpts` parameter, allowing callers to provide `onSuccess`, `onError`, `onSettled`, and other mutation options
- Added shared `MutationOpts` type (`frontend/src/types/mutation.ts`)
- Fixed `apiMutator` to merge request options (custom headers were silently ignored)
- Optimized database indexes: dropped 9 redundant indexes (PK-subsumed and unique-constraint-duplicated) and added 6 high-priority FK/reverse-lookup indexes for `task_assignees`, `initiative_members`, `project_permissions`, `document_permissions`, `initiatives`, and `projects`
- Synced model declarations (`index=True`) with actual database indexes for maintainability
- Test database setup is now fully automatic — `conftest.py` creates the `initiative_test` database and runs migrations on first test run, removing the need for manual `setup_test_db.sh`
- Centralized document mutations into `useDocuments.ts` — new hooks for create, upload, duplicate, copy, member CRUD (individual + bulk), role permission CRUD, and AI summary generation; replaces inline mutations across DocumentSettingsPage, DocumentDetailPage, DocumentsPage, CreateDocumentDialog, CreateWikilinkDocumentDialog, and DocumentSummary
- Centralized initiative mutations into `useInitiatives.ts` with `MutationOpts` support — replaces inline mutations in InitiativeSettingsPage

## [0.31.4] - 2026-02-20

### Fixed

- Mobile (Capacitor) app crash on startup — Orval-generated API requests used a hardcoded empty `baseURL`, causing them to hit the WebView origin instead of the backend server and receiving HTML instead of JSON
- Race condition where child provider effects fired API calls before `ServerProvider` set the backend URL from storage
- Locale file 404s on mobile — `navigator.language` returns full locale codes (e.g., `en-US`) but only `en/` directories exist; added `load: "languageOnly"` to i18next config
- `useProjectFavoriteMutation` and `useProjectPinMutation` crashing when toggling — `setQueryData` updaters treated paginated `ProjectListResponse` as a plain array
- Defensive `Array.isArray` guard in `initStorage()` and AppSidebar favorites to prevent crashes from unexpected Capacitor bridge responses

## [0.31.3] - 2026-02-20

### Added

- Paginated `GET /api/v1/projects/` endpoint with `page` and `page_size` query params (`page_size=0` returns all, preserving backward compatibility)
- `MentionEntityType` enum for mention search endpoint — replaces open-ended string parameter
- `PermissionKey` enum enforced at API, model, and database levels — adds CHECK constraint to `initiative_role_permissions.permission_key` column
- Alembic migration to add CHECK constraint for valid `permission_key` values

### Changed

- Centralized remaining inline queries — `GuildDashboardPage`, `MyProjectsPage`, `MyDocumentsPage` now use domain hooks (`useProjects`, `useInitiatives`, `useTasks`, `useRecentComments`, `useGlobalProjects`, `useGlobalDocuments`)
- Eliminated direct `useQueryClient` usage from pages/components — added `usePrefetchTasks`, `usePrefetchGlobalProjects`, `usePrefetchGlobalDocuments`, `usePrefetchDocumentsList`, `useSetDocumentCache`, `useCommentsCache`, and `useUpdateRoleLabels` hooks
- Added ESLint rule (`no-restricted-imports`) to prevent direct `useQuery`/`useQueryClient` imports outside `src/api/` and `src/hooks/`
- Migrated `useGlobalProjects` from raw `apiClient` to Orval-generated `listGlobalProjectsApiV1ProjectsGlobalGet` with generated query keys
- Removed custom `ProjectListResponse`, `MentionEntityType`, and `PermissionKey` types from `frontend/src/types/api.ts` — now generated from backend OpenAPI spec
- Moved `TaskWeekPosition` to `lib/recurrence.ts` and `CommentWithReplies` to `CommentSection.tsx` — `types/api.ts` is now a pure re-export of generated schemas

### Fixed

- Template document dropdown in CreateDocumentDialog not showing templates accessible via role-based permissions (only showed templates with explicit user permissions)
- Document/attachment uploads returning 422 error due to hardcoded `Content-Type: application/json` header overriding FormData auto-detection
- Subtask checklist items failed to load ("Unable to load checklist items right now") due to double-unwrapping of API responses in `useSubtasks` hook and `TaskChecklist` mutations

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
