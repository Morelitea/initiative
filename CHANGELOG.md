# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
