/**
 * Centralized query-key invalidation helpers.
 *
 * Orval generates URL-based query keys (e.g. ["/api/v1/tags/"]).
 * This module provides domain-specific helpers that use `predicate`-based
 * matching so a single invalidation call can reach both list and detail keys.
 *
 * Guild isolation is handled by the X-Guild-ID header interceptor on apiClient;
 * query keys don't embed guild IDs because the cache is cleared on guild switch.
 */
import { queryClient } from "@/lib/queryClient";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Invalidate all queries whose first key segment starts with the given prefix. */
const invalidatePrefix = (prefix: string) =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const first = query.queryKey[0];
      return typeof first === "string" && first.startsWith(prefix);
    },
  });

/** Invalidate a single query by its exact key. */
const invalidateExact = (queryKey: readonly unknown[]) =>
  queryClient.invalidateQueries({ queryKey: queryKey as unknown[] });

// ── Tags ─────────────────────────────────────────────────────────────────────

export const invalidateAllTags = () => invalidatePrefix("/api/v1/tags");

export const invalidateTag = (tagId: number) => invalidateExact([`/api/v1/tags/${tagId}`]);

export const invalidateTagEntities = (tagId: number) =>
  invalidateExact([`/api/v1/tags/${tagId}/entities`]);

// ── Tasks ────────────────────────────────────────────────────────────────────

export const invalidateAllTasks = () => invalidatePrefix("/api/v1/tasks");

export const invalidateTask = (taskId: number) => invalidateExact([`/api/v1/tasks/${taskId}`]);

export const invalidateTaskSubtasks = (taskId: number) =>
  invalidateExact([`/api/v1/tasks/${taskId}/subtasks`]);

// ── Projects ─────────────────────────────────────────────────────────────────

export const invalidateAllProjects = () => invalidatePrefix("/api/v1/projects");

export const invalidateProject = (projectId: number) =>
  invalidateExact([`/api/v1/projects/${projectId}`]);

export const invalidateProjectTaskStatuses = (projectId: number) =>
  invalidateExact([`/api/v1/projects/${projectId}/task-statuses/`]);

export const invalidateProjectActivity = (projectId: number) =>
  invalidateExact([`/api/v1/projects/${projectId}/activity`]);

export const invalidateRecentProjects = () => invalidateExact([`/api/v1/projects/recent`]);

export const invalidateFavoriteProjects = () => invalidateExact([`/api/v1/projects/favorites`]);

export const invalidateWritableProjects = () => invalidateExact([`/api/v1/projects/writable`]);

// ── Documents ────────────────────────────────────────────────────────────────

export const invalidateAllDocuments = () => invalidatePrefix("/api/v1/documents");

export const invalidateDocument = (documentId: number) =>
  invalidateExact([`/api/v1/documents/${documentId}`]);

export const invalidateDocumentBacklinks = (documentId: number) =>
  invalidateExact([`/api/v1/documents/${documentId}/backlinks`]);

// ── Comments ─────────────────────────────────────────────────────────────────

export const invalidateAllComments = () => invalidatePrefix("/api/v1/comments");

export const invalidateTaskComments = (taskId: number) =>
  queryClient.invalidateQueries({
    predicate: (query) => {
      const [url, params] = query.queryKey;
      return (
        url === "/api/v1/comments/" &&
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
        url === "/api/v1/comments/" &&
        typeof params === "object" &&
        params !== null &&
        (params as Record<string, unknown>).document_id === documentId
      );
    },
  });

export const invalidateRecentComments = () => invalidatePrefix("/api/v1/comments/recent");

// ── Notifications ────────────────────────────────────────────────────────────

export const invalidateNotifications = () => invalidatePrefix("/api/v1/notifications");

// ── Initiatives ──────────────────────────────────────────────────────────────

export const invalidateAllInitiatives = () => invalidatePrefix("/api/v1/initiatives");

export const invalidateInitiative = (initiativeId: number) =>
  invalidateExact([`/api/v1/initiatives/${initiativeId}`]);

export const invalidateInitiativeRoles = (initiativeId: number) =>
  invalidateExact([`/api/v1/initiatives/${initiativeId}/roles`]);

export const invalidateMyPermissions = (initiativeId: number) =>
  invalidateExact([`/api/v1/initiatives/${initiativeId}/my-permissions`]);

export const invalidateInitiativeMembers = (initiativeId: number) =>
  invalidateExact([`/api/v1/initiatives/${initiativeId}/members`]);

// ── Settings ─────────────────────────────────────────────────────────────────

export const invalidateAllSettings = () => invalidatePrefix("/api/v1/settings");

export const invalidateRoleLabels = () => invalidateExact([`/api/v1/settings/roles`]);

export const invalidateInterfaceSettings = () => invalidateExact([`/api/v1/settings/interface`]);

export const invalidateEmailSettings = () => invalidateExact([`/api/v1/settings/email`]);

export const invalidateAuthSettings = () => invalidateExact([`/api/v1/settings/auth`]);

export const invalidateOidcMappings = () => invalidatePrefix("/api/v1/settings/oidc-mappings");

// ── AI Settings ──────────────────────────────────────────────────────────────

export const invalidateAllAISettings = () => invalidatePrefix("/api/v1/settings/ai");

export const invalidatePlatformAISettings = () => invalidateExact([`/api/v1/settings/ai/platform`]);

export const invalidateGuildAISettings = () => invalidateExact([`/api/v1/settings/ai/guild`]);

export const invalidateUserAISettings = () => invalidateExact([`/api/v1/settings/ai/user`]);

export const invalidateResolvedAISettings = () => invalidateExact([`/api/v1/settings/ai/resolved`]);

// ── Users / Admin ────────────────────────────────────────────────────────────

export const invalidateCurrentUser = () => invalidateExact([`/api/v1/users/me`]);

export const invalidateUserStats = () => invalidatePrefix("/api/v1/users/me/stats");

export const invalidateUsersList = () => invalidateExact([`/api/v1/users/`]);

export const invalidateAdminUsers = () => invalidatePrefix("/api/v1/admin");

// ── Guilds ───────────────────────────────────────────────────────────────────

export const invalidateAllGuilds = () => invalidatePrefix("/api/v1/guilds");

export const invalidateGuildInvites = (guildId: number) =>
  invalidateExact([`/api/v1/guilds/${guildId}/invites`]);

// ── Guild Switch ────────────────────────────────────────────────────────────
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

// ── Queues ──────────────────────────────────────────────────────────────────

export const invalidateAllQueues = () => invalidatePrefix("/api/v1/queues");

export const invalidateQueue = (queueId: number) => invalidateExact([`/api/v1/queues/${queueId}`]);

// ── Subtasks ─────────────────────────────────────────────────────────────────

export const invalidateSubtask = (subtaskId: number) =>
  invalidateExact([`/api/v1/subtasks/${subtaskId}`]);

// ── Version ──────────────────────────────────────────────────────────────────

export const invalidateVersion = () => invalidateExact([`/api/v1/version`]);

export const invalidateLatestVersion = () => invalidateExact([`/api/v1/version/latest`]);

// ── Task Statuses ────────────────────────────────────────────────────────────

export const invalidateAllTaskStatuses = () => invalidatePrefix("/api/v1/projects");
