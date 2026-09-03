/**
 * Centralized query-key invalidation helpers.
 *
 * NAMING — the UI calls these "communities"; the code calls them guilds.
 * Communities ended up being used far more broadly than the gaming guilds the
 * name was picked for, so the product renamed them. The rename stopped at the
 * user-visible strings: the database, the API, the generated client and every
 * identifier below still say `guild`, because moving those means a schema
 * migration across every tenant. Treat `guild` in code and `community` in copy
 * as the same thing. This is deliberate and permanent, not a half-finished
 * rename -- if you are adding UI, say community; if you are adding a query,
 * follow the `guild` that is already here.
 *
 * Orval generates URL-based query keys (e.g. ["/api/v1/tags/"]). This module
 * provides domain-specific helpers that use `predicate`-based matching so a
 * single invalidation call can reach both list and detail keys.
 *
 * There are TWO disjoint families of keys, and invalidation MUST NOT cross
 * between them:
 *
 *  - GUILD-scoped keys live under `/api/v1/g/{guildId}/...`. The `invalidateGuild*`
 *    helpers match these and ONLY for the ACTIVE guild — never another guild, and
 *    never a non-guild key. This is the tenancy boundary: a mutation in one guild
 *    can't touch another guild's (or a personal) cached data.
 *  - PERSONAL / platform keys are everything else (`/api/v1/me/*`, `/settings`,
 *    `/users`, `/guilds`, `/admin`, `/notifications`, `/version`, `/recents`).
 *    The `invalidatePersonal*` helpers match these and ONLY these — never a
 *    `/api/v1/g/...` key.
 *
 * A few resources genuinely span both (a guild list plus its cross-guild `/me`
 * aggregate; platform + guild AI settings). Those compose the two families with
 * an explicit `Promise.all` — two boundary-respecting calls, never one matcher
 * that blurs the line.
 */
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { queryClient } from "@/lib/queryClient";

// The active guild is per-tab React state in `GuildProvider`, mirrored here (a
// module var is per-JS-context, so it stays per-tab — unlike shared storage) so
// the guild matchers can scope without every call site threading a guild id.
let scopedGuildId: number | null = null;

/** Mirror this tab's active guild so guild invalidation stays scoped to it. */
export const setInvalidationGuild = (guildId: number | null) => {
  scopedGuildId = guildId && guildId > 0 ? guildId : null;
};

// ── Guild-scoped matching ─────────────────────────────────────────────────────

/**
 * The active guild's relative path for a guild-scoped key, else null:
 * `/api/v1/g/{active}/<r>` → `/api/v1/<r>`; another guild's key or a non-guild
 * key → null (never matches). With no active guild, any guild's key matches.
 */
const guildKey = (key: unknown): string | null => {
  if (typeof key !== "string") return null;
  const match = key.match(/^\/api\/v1\/g\/(\d+)(\/.*)?$/);
  if (!match) return null;
  if (scopedGuildId !== null && Number(match[1]) !== scopedGuildId) return null;
  return `/api/v1${match[2] ?? ""}`;
};

const invalidateGuildPrefix = (prefix: string) =>
  queryClient.invalidateQueries({
    predicate: (q) => guildKey(q.queryKey[0])?.startsWith(prefix) ?? false,
  });

const invalidateGuildExact = (queryKey: readonly unknown[]) =>
  queryClient.invalidateQueries({
    predicate: (q) => guildKey(q.queryKey[0]) === queryKey[0],
  });

// ── Personal / platform matching ──────────────────────────────────────────────

/** A non-guild key as-is, or null for any `/api/v1/g/...` (guild-scoped) key. */
const personalKey = (key: unknown): string | null => {
  if (typeof key !== "string") return null;
  if (/^\/api\/v1\/g\/\d+/.test(key)) return null;
  return key;
};

const invalidatePersonalPrefix = (prefix: string) =>
  queryClient.invalidateQueries({
    predicate: (q) => personalKey(q.queryKey[0])?.startsWith(prefix) ?? false,
  });

const invalidatePersonalExact = (queryKey: readonly unknown[]) =>
  queryClient.invalidateQueries({
    predicate: (q) => personalKey(q.queryKey[0]) === queryKey[0],
  });

/**
 * Invalidate a resource across BOTH its guild-scoped list and its cross-guild
 * "my" aggregate — two distinct, boundary-respecting calls. The guild leg stays
 * scoped to the active guild; the `/api/v1/me/<r>` leg is personal, so a single
 * resource prefix never reaches it and it must be invalidated explicitly or the
 * "my <resource>" list goes stale until remount.
 */
const invalidateResourceAndMe = (resource: string) =>
  Promise.all([
    invalidateGuildPrefix(`/api/v1/${resource}`),
    invalidatePersonalPrefix(`/api/v1/me/${resource}`),
  ]);

// ── Announcements (platform) ─────────────────────────────────────────────────

/** Both the reader's queue and the authoring list — one write moves both. */
export const invalidateAnnouncements = () => invalidatePersonalPrefix("/api/v1/announcements");

// ── Tags (guild) ──────────────────────────────────────────────────────────────

export const invalidateAllTags = () => invalidateGuildPrefix("/api/v1/tags");

export const invalidateTag = (tagId: number) => invalidateGuildExact([`/api/v1/tags/${tagId}`]);

export const invalidateTagEntities = (tagId: number) =>
  invalidateGuildExact([`/api/v1/tags/${tagId}/entities`]);

// ── Tasks (guild + me) ──────────────────────────────────────────────────────────

// Also refreshes the calendar-entries aggregate (a derived events+tasks view),
// so a task mutation reflects on the calendar surfaces.
export const invalidateAllTasks = () =>
  Promise.all([invalidateResourceAndMe("tasks"), invalidateResourceAndMe("calendar-entries")]);

export const invalidateTask = (taskId: number) => invalidateGuildExact([`/api/v1/tasks/${taskId}`]);

export const invalidateTaskSubtasks = (taskId: number) =>
  invalidateGuildExact([`/api/v1/tasks/${taskId}/subtasks`]);

// ── Projects (guild + me) ────────────────────────────────────────────────────────

export const invalidateAllProjects = () => invalidateResourceAndMe("projects");

export const invalidateProject = (projectId: number) =>
  invalidateGuildExact([`/api/v1/projects/${projectId}`]);

export const invalidateProjectTaskStatuses = (projectId: number) =>
  invalidateGuildExact([`/api/v1/projects/${projectId}/task-statuses/`]);

export const invalidateProjectFilterPresets = (projectId: number) =>
  invalidateGuildExact([`/api/v1/projects/${projectId}/filter-presets/`]);

export const invalidateProjectActivity = (projectId: number) =>
  invalidateGuildExact([`/api/v1/projects/${projectId}/activity`]);

// Recents list is a cross-guild personal endpoint (`/api/v1/recents/`, no /g/).
export const invalidateRecents = () => invalidatePersonalExact([`/api/v1/recents/`]);

export const invalidateFavoriteProjects = () =>
  invalidateGuildExact([`/api/v1/projects/favorites`]);

export const invalidateWritableProjects = () => invalidateGuildExact([`/api/v1/projects/writable`]);

// ── Documents (guild + me) ───────────────────────────────────────────────────────

export const invalidateAllDocuments = () => invalidateResourceAndMe("documents");

export const invalidateDocument = (documentId: number) =>
  invalidateGuildExact([`/api/v1/documents/${documentId}`]);

export const invalidateDocumentBacklinks = (documentId: number) =>
  invalidateGuildExact([`/api/v1/documents/${documentId}/backlinks`]);

export const invalidateDocumentVersions = (documentId: number) =>
  invalidateGuildExact([`/api/v1/documents/${documentId}/versions`]);

// ── Comments (guild) ────────────────────────────────────────────────────────────

export const invalidateAllComments = () => invalidateGuildPrefix("/api/v1/comments");

export const invalidateTaskComments = (taskId: number) =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const [url, params] = query.queryKey;
      return (
        guildKey(url) === "/api/v1/comments/" &&
        typeof params === "object" &&
        params !== null &&
        (params as Record<string, unknown>).task_id === taskId
      );
    },
  });

export const invalidateDocumentComments = (documentId: number) =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const [url, params] = query.queryKey;
      return (
        guildKey(url) === "/api/v1/comments/" &&
        typeof params === "object" &&
        params !== null &&
        (params as Record<string, unknown>).document_id === documentId
      );
    },
  });

export const invalidateRecentComments = () => invalidateGuildPrefix("/api/v1/comments/recent");

// ── Notifications (personal) ─────────────────────────────────────────────────────

export const invalidateNotifications = () => invalidatePersonalPrefix("/api/v1/notifications");

// ── Contacts: who may reach you, and who you have agreed with ────────────────────

/** The policy and its per-community toggles. */
export const invalidateDmSettings = () => invalidatePersonalExact(["/api/v1/me/dm-settings"]);

/** Connections and message requests — one channel moves both. */
export const invalidateContactGrants = () => {
  void invalidatePersonalPrefix("/api/v1/me/connections");
  return invalidatePersonalPrefix("/api/v1/me/message-requests");
};

/** The accounts this person has chosen not to hear from. */
export const invalidateIgnoredAccounts = () => invalidatePersonalPrefix("/api/v1/me/ignored");

/** Everyone the reader may reach: the community sections and the starred list. */
export const invalidateContacts = () => invalidatePersonalPrefix("/api/v1/me/contacts");

/**
 * The direct-message mailbox.
 *
 * Keyed on ``["dm", ...]`` rather than a path, because a thread is read out of
 * this device's own store rather than from an endpoint — the server deletes a
 * message once it has been collected.
 */
export const invalidateDirectMessages = () => queryClient.invalidateQueries({ queryKey: ["dm"] });

// ── Initiatives (guild) ──────────────────────────────────────────────────────────

export const invalidateAllInitiatives = () => invalidateGuildPrefix("/api/v1/initiatives");

export const invalidateInitiative = (initiativeId: number) =>
  invalidateGuildExact([`/api/v1/initiatives/${initiativeId}`]);

export const invalidateInitiativeRoles = (initiativeId: number) =>
  invalidateGuildExact([`/api/v1/initiatives/${initiativeId}/roles`]);

export const invalidateMyPermissions = (initiativeId: number) =>
  invalidateGuildExact([`/api/v1/initiatives/${initiativeId}/my-permissions`]);

export const invalidateInitiativeMembers = (initiativeId: number) =>
  invalidateGuildExact([`/api/v1/initiatives/${initiativeId}/members`]);

// One prefix reaches every reader of the queue: the manager's list (keyed with
// its `status` filter), the requester's own `/me` rows, and any narrower status
// view — so a request or an answer never leaves one of them showing the old
// truth. The directory's own badge rides on `invalidateAllInitiatives`.
export const invalidateInitiativeJoinRequests = (initiativeId: number) =>
  invalidateGuildPrefix(`/api/v1/initiatives/${initiativeId}/join-requests`);

// ── Settings (personal / platform) ───────────────────────────────────────────────

// "All settings" is a blunt flush spanning two DELIBERATELY separate backend
// scopes: app/platform config (`/api/v1/settings/*`, owner-only) and a guild's
// AI settings (`/api/v1/g/{id}/settings/ai/*`, RLS-scoped). They live on
// different paths by design — app config isn't guild-specific, and guild AI
// settings must carry guild context — so compose both families here rather than
// let one matcher cross the boundary. (This is not a backend inconsistency.)
export const invalidateAllSettings = () =>
  Promise.all([
    invalidatePersonalPrefix("/api/v1/settings"),
    invalidateGuildPrefix("/api/v1/settings"),
  ]);

export const invalidateInterfaceSettings = () =>
  invalidatePersonalExact([`/api/v1/settings/interface`]);

export const invalidateEmailSettings = () => invalidatePersonalExact([`/api/v1/settings/email`]);

export const invalidateAuthSettings = () => invalidatePersonalExact([`/api/v1/settings/auth`]);

export const invalidateAuthProviders = () =>
  invalidatePersonalExact([`/api/v1/settings/auth/providers/`]);

export const invalidateStorageSettings = () =>
  invalidatePersonalExact([`/api/v1/settings/storage`]);

// The community-directory switch is written under /settings but read from the
// SPA's boot config, so an owner's write has to reach the config key rather
// than a settings one.
export const invalidateAppConfig = () => invalidatePersonalExact([`/api/v1/config`]);

/** The owner's own read of the three community-wide decisions. */
export const invalidateCommunitySettings = () =>
  invalidatePersonalExact([`/api/v1/settings/community`]);

export const invalidateOidcMappings = () =>
  invalidatePersonalPrefix("/api/v1/settings/oidc-mappings");

// The platform Guilds tab reads/writes only shared public tables (owner-only),
// so its list lives in the personal/platform family, not under any /g/ key.
export const invalidatePlatformGuilds = () => invalidatePersonalExact([`/api/v1/settings/guilds`]);

// ── App services (personal / platform) ───────────────────────────────────────
// Orval keys the list as `/api/v1/app-services/` (trailing slash) and each row
// as `/api/v1/app-services/{id}` (no slash), so they are siblings rather than a
// prefix pair. Match on the shared path so one call reaches the list and every
// detail read.
export const invalidateAppServices = () => invalidatePersonalPrefix("/api/v1/app-services");

// ── AI Settings (platform config is personal; guild/member/resolved are guild-scoped) ──

export const invalidateAllAISettings = () =>
  Promise.all([
    invalidatePersonalPrefix("/api/v1/settings/ai"),
    invalidateGuildPrefix("/api/v1/settings/ai"),
  ]);

// The platform owner's global mode + `allow_member_keys` (personal/platform).
export const invalidatePlatformAIMode = () =>
  invalidatePersonalExact([`/api/v1/settings/ai/platform/mode`]);

// The operator-defined connections list (personal/platform).
export const invalidatePlatformAIConnections = () =>
  invalidatePersonalExact([`/api/v1/settings/ai/platform/connections`]);

// A guild admin's own connections list (guild-scoped: `/g/{id}/settings/ai/connections`).
export const invalidateGuildAIConnections = () =>
  invalidateGuildExact([`/api/v1/settings/ai/connections`]);

// The member's own view: selected connection, per-connection key state, on/off.
export const invalidateMemberAI = () => invalidateGuildExact([`/api/v1/settings/ai/me`]);

export const invalidateResolvedAISettings = () =>
  invalidateGuildExact([`/api/v1/settings/ai/resolved`]);

// The cross-guild personal aggregate powering the "My AI" page (a flat `/me/ai`
// list across every guild the user belongs to) — personal, never guild-scoped.
export const invalidateMyAI = () => invalidatePersonalExact([`/api/v1/me/ai`]);

// ── Users / Admin (personal / platform) ──────────────────────────────────────────

export const invalidateCurrentUser = () => invalidatePersonalExact([`/api/v1/users/me`]);

export const invalidateUserStats = () => invalidatePersonalPrefix("/api/v1/me/stats");

export const invalidateAdminUsers = () => invalidatePersonalPrefix("/api/v1/admin");

// ── Guild Members (guild) ─────────────────────────────────────────────────────────
// The member roster is guild-scoped (`/api/v1/g/{id}/users/`), even though the
// membership *mutations* go through the platform `/api/v1/guilds/{id}/members/...`
// path. Invalidating it must stay in the guild bucket.

export const invalidateGuildMembers = () => invalidateGuildExact([`/api/v1/users/`]);

// ── Guilds (personal / platform) ─────────────────────────────────────────────────

export const invalidateAllGuilds = () => invalidatePersonalPrefix("/api/v1/guilds");

export const invalidateGuildInvites = (guildId: number) =>
  invalidatePersonalExact([`/api/v1/guilds/${guildId}/invites`]);

// ── Guild Switch ──────────────────────────────────────────────────────────────
// Keys that are NOT guild-scoped and should survive a guild switch.
// `/api/v1/recents` is one of them: the recents bar is a cross-guild personal
// list, so switching community neither changes its contents nor invalidates
// them. Resetting it made the bar blank and refetch on every switch, dropping
// tabs that belong to the community being left as well as the one arriving.
const GLOBAL_KEY_PREFIXES = [
  "/api/v1/guilds",
  "/api/v1/users/me",
  "/api/v1/version",
  "/api/v1/recents",
];

/** Remove all guild-scoped query data so stale cross-guild results are never shown. */
export const resetGuildScopedQueries = () =>
  queryClient.resetQueries({
    predicate: (query) => {
      const first = query.queryKey[0];
      if (typeof first !== "string") return true;
      return !GLOBAL_KEY_PREFIXES.some((prefix) => first.startsWith(prefix));
    },
  });

// ── Queues (guild) ──────────────────────────────────────────────────────────────

export const invalidateAllQueues = () => invalidateGuildPrefix("/api/v1/queues");

export const invalidateQueue = (queueId: number) =>
  invalidateGuildExact([`/api/v1/queues/${queueId}`]);

// ── Counter Groups (guild) ────────────────────────────────────────────────────────

export const invalidateAllCounterGroups = () => invalidateGuildPrefix("/api/v1/counter-groups");

export const invalidateCounterGroup = (groupId: number) =>
  invalidateGuildExact([`/api/v1/counter-groups/${groupId}`]);

// ── Calendars & Calendar Events (guild + me) ──────────────────────────────────────

// The calendar-entries aggregate unions events + task markers; refresh it too so
// event mutations reflect on the calendar surfaces.
export const invalidateAllCalendarEntries = () => invalidateResourceAndMe("calendar-entries");

export const invalidateAllCalendarEvents = () =>
  Promise.all([invalidateResourceAndMe("calendar-events"), invalidateAllCalendarEntries()]);

export const invalidateCalendarEvent = (eventId: number) =>
  invalidateGuildExact([`/api/v1/calendar-events/${eventId}`]);

// Calendar (the container) mutations also refresh the events + entries views —
// renames/colors/sharing change what those surfaces show.
export const invalidateAllCalendars = () =>
  Promise.all([invalidateGuildPrefix("/api/v1/calendars"), invalidateAllCalendarEvents()]);

export const invalidateCalendar = (calendarId: number) =>
  invalidateGuildExact([`/api/v1/calendars/${calendarId}`]);

// ── Dashboards (guild) ────────────────────────────────────────────────────────────

export const invalidateAllDashboards = () => invalidateGuildPrefix("/api/v1/dashboards");

export const invalidateDashboard = (dashboardId: number) =>
  invalidateGuildExact([`/api/v1/dashboards/${dashboardId}`]);

// ── Subtasks (guild) ──────────────────────────────────────────────────────────────

export const invalidateSubtask = (subtaskId: number) =>
  invalidateGuildExact([`/api/v1/subtasks/${subtaskId}`]);

// ── Version (personal) ────────────────────────────────────────────────────────────

export const invalidateVersion = () => invalidatePersonalExact([`/api/v1/version`]);

export const invalidateLatestVersion = () => invalidatePersonalExact([`/api/v1/version/latest`]);

// ── Task Statuses (guild) ─────────────────────────────────────────────────────────

export const invalidateAllTaskStatuses = () => invalidateGuildPrefix("/api/v1/projects");

// ── Properties (guild) ────────────────────────────────────────────────────────────

export const invalidateAllProperties = () => invalidateGuildPrefix("/api/v1/property-definitions");

// ── Initiative membership (guild, cross-tool) ────────────────────────────────────
// Gaining (or losing) a membership row changes what the guild returns for every
// tool, not just the initiative list: the sidebar tree, the discovery directory,
// and each tool's guild-wide list all read differently afterwards. Declared last
// so it can compose the per-resource helpers above.

export const invalidateInitiativeMembership = () =>
  Promise.all([
    invalidateAllInitiatives(),
    invalidateAllProjects(),
    invalidateAllDocuments(),
    invalidateAllQueues(),
    invalidateAllCounterGroups(),
    invalidateAllCalendars(),
    invalidateAllDashboards(),
  ]);

// ── One tool entity (guild, cross-tool) ─────────────────────────────────────────
// What every generic per-tool mutation — set tags, flip the comment switch —
// has to refresh: that tool's list and detail queries. `Record<Tool, …>` so a
// new Tool member fails to compile until it declares its invalidation. Declared
// last so it can compose the per-resource helpers above.

const TOOL_INVALIDATORS: Record<Tool, (id: number) => void> = {
  [Tool.project]: (id) => {
    void invalidateProject(id);
    void invalidateAllProjects();
  },
  [Tool.document]: (id) => {
    void invalidateDocument(id);
    void invalidateAllDocuments();
  },
  [Tool.queue]: (id) => {
    void invalidateQueue(id);
    void invalidateAllQueues();
  },
  [Tool.counter_group]: (id) => {
    void invalidateCounterGroup(id);
    void invalidateAllCounterGroups();
  },
  [Tool.calendar]: (id) => {
    void invalidateCalendar(id);
    void invalidateAllCalendars();
  },
  [Tool.dashboard]: (id) => {
    void invalidateDashboard(id);
    void invalidateAllDashboards();
  },
};

export const invalidateTool = (tool: Tool, id: number) => TOOL_INVALIDATORS[tool](id);
