# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
