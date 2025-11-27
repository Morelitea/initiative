1. Data Model & Migration Plan
   New tables

guilds: id, name, slug (optional), description, icon_base64, created_at/updated_at, created_by_user_id.
guild_memberships: guild_id, user_id, role (admin | member), timestamps. Enforce unique (guild_id, user_id).
guild_invites: id, unique code, guild_id, created_by_user_id, expires_at, max_uses, uses, optional invitee_email.
Existing tables

initiatives: add guild_id FK (non-null). Drop global unique constraint on name and replace with (guild_id, lower(name)).
users: add active_guild_id FK, drop or ignore role column (kept for migrations but no longer authoritative).
app_settings: eventually becomes per-guild (either move columns to guild_settings or add guild_id). For the first pass we can keep a global row and mirror values onto each guild via a new table.
Migration steps

Create guilds/memberships/invites tables + guild_role enum.
Insert a “Primary Guild” row; for every existing user insert a guild_memberships row using their current user.role, and set users.active_guild_id.
Update all initiatives to reference this guild.
(Optional) seed guild settings rows.
This migration occurs before later schema changes (it will branch off 20240802_0015_project_member_write.py).

2. Backend Surface Area
   Config / ENV

Add DISABLE_GUILD_CREATION (default False).
Add DEFAULT_GUILD_ICON? optional.
Models & Services

New app/models/guild.py.
Extend User with active_guild_id, guild_memberships relationship.
Extend Initiative with guild_id.
Services:
guilds.py: create guild, list guilds for user, set active guild, ensure membership, invite issuance/consumption.
Update initiatives_service.ensure_default_initiative to work per guild and rely on guild membership.
Dependencies

Add get_current_guild_context that:
Reads X-Guild-ID header (or query param) if provided.
Falls back to user.active_guild_id else first membership.
Ensures the user has membership; returns guild, membership, role.
Endpoints

Introduce /guilds router:
GET /guilds: list user’s guilds + membership role/active flag.
POST /guilds: create (blocked if env disables).
POST /guilds/{guild_id}/switch: updates active_guild_id.
POST /guilds/{guild_id}/invites: create invites.
POST /guilds/invite/accept: redeem invite code (either existing user joins or new registration uses invite).
Update existing routers (initiatives, projects, tasks, users, settings, notifications) to accept the guild context and scope queries via guild_id.
Auth / Registration

UserCreate gains optional invite_code.
Flow:
If DISABLE_GUILD_CREATION is true, require invite_code, validate GuildInvite, join that guild, set active_guild_id, increment uses.
Else, if invite provided use it; otherwise create “<Full Name|Email>’s Guild”, add user as guild admin, set their active guild.
Permissions

Replace direct user.role == UserRole.admin checks with membership checks from the guild context (membership.role == GuildRole.admin). Initiative-level PM/member logic stays, but it’s also scoped inside the guild (i.e., initiatives can only belong to the current guild). 3. Frontend Changes
Global State

Add a Guild context/provider (e.g., GuildProvider) that fetches /guilds, stores the current guild, and exposes switchGuild, createGuild, invites.
Update apiClient to set X-Guild-ID header via a setCurrentGuildId() helper.
Auth Flow

When login completes, load guilds; if the user lacks an active guild, fallback to the first membership and notify backend via /guilds/{id}/switch.
Registration form now includes invite-code handling; if creation enabled offer “Create new guild” vs “Join via invite code”.
UI Shell

Replace the current top nav/side layout with a Discord-style vertical guild switcher:
Displays guild icons (Base64) or initials.

- button to create guild (if env allows).
  Secondary sidebar shows initiatives per guild (existing list stays mostly same but filtered by selected guild).
  Guild Admin UX

Provide a settings screen to edit guild details (name/icon).
Expose invite creation UI (generate code, expiry, uses) and list active invites.
Existing Screens

Everywhere we show “Admin / Project manager / Member” text, use useRoleLabels but now referencing guild context where relevant (already started earlier).
Update “Users” settings page to list only members of the active guild, with role dropdown derived from GuildMembership.role.
Projects/Initiatives pages already filter by initiative membership; ensure the queries include guild_id. 4. Testing & Migration Strategy
Need fixture data covering: multi-guild user, guild creation disabled (invite path), guild-level admin vs member.
Backend: update pytest fixtures for guild context, add tests for new dependency and registration flows.
Frontend: update MSW mocks or test harness to include guild endpoints.
