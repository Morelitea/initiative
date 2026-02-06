# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Bulk edit tags for tasks and documents (add/remove modes)
- Bulk edit access permissions for documents (grant/revoke modes)

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
