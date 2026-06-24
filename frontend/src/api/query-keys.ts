/**
 * Centralized query-key invalidation helpers.
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

// ── Tags (guild) ──────────────────────────────────────────────────────────────

export const invalidateAllTags = () => invalidateGuildPrefix("/api/v1/tags");

export const invalidateTag = (tagId: number) => invalidateGuildExact([`/api/v1/tags/${tagId}`]);

export const invalidateTagEntities = (tagId: number) =>
  invalidateGuildExact([`/api/v1/tags/${tagId}/entities`]);

// ── Tasks (guild + me) ──────────────────────────────────────────────────────────

export const invalidateAllTasks = () => invalidateResourceAndMe("tasks");

export const invalidateTask = (taskId: number) => invalidateGuildExact([`/api/v1/tasks/${taskId}`]);

export const invalidateTaskSubtasks = (taskId: number) =>
  invalidateGuildExact([`/api/v1/tasks/${taskId}/subtasks`]);

// ── Projects (guild + me) ────────────────────────────────────────────────────────

export const invalidateAllProjects = () => invalidateResourceAndMe("projects");

export const invalidateProject = (projectId: number) =>
  invalidateGuildExact([`/api/v1/projects/${projectId}`]);

export const invalidateProjectTaskStatuses = (projectId: number) =>
  invalidateGuildExact([`/api/v1/projects/${projectId}/task-statuses/`]);

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

export const invalidateOidcMappings = () =>
  invalidatePersonalPrefix("/api/v1/settings/oidc-mappings");

// ── AI Settings (platform is personal; guild/user/resolved are guild-scoped) ──────

export const invalidateAllAISettings = () =>
  Promise.all([
    invalidatePersonalPrefix("/api/v1/settings/ai"),
    invalidateGuildPrefix("/api/v1/settings/ai"),
  ]);

export const invalidatePlatformAISettings = () =>
  invalidatePersonalExact([`/api/v1/settings/ai/platform`]);

export const invalidateGuildAISettings = () => invalidateGuildExact([`/api/v1/settings/ai/guild`]);

export const invalidateUserAISettings = () => invalidateGuildExact([`/api/v1/settings/ai/user`]);

export const invalidateResolvedAISettings = () =>
  invalidateGuildExact([`/api/v1/settings/ai/resolved`]);

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
// Keys that are NOT guild-scoped and should survive a guild switch
const GLOBAL_KEY_PREFIXES = ["/api/v1/guilds", "/api/v1/users/me", "/api/v1/version"];

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

// ── Calendar Events (guild + me) ──────────────────────────────────────────────────

export const invalidateAllCalendarEvents = () => invalidateResourceAndMe("calendar-events");

export const invalidateCalendarEvent = (eventId: number) =>
  invalidateGuildExact([`/api/v1/calendar-events/${eventId}`]);

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
