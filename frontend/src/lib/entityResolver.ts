/**
 * Turning a bare entity id into the URL that addresses it.
 *
 * Every tool entity now lives inside its initiative — `/i/{initiative}/{tool}/{id}` —
 * so a link needs the whole chain, not just the id. Most callers already hold
 * the parent and should build the route directly with `lib/tools.ts`. A few
 * genuinely can't: a `@mention` is an id embedded in comment text, a queue
 * item's linked entity is a bare id, and a notification's target path was
 * written to the database before anyone knew where the entity would live.
 *
 * Those go through `/go/{refType}/{id}`, whose loader calls
 * {@link resolveEntityPath} and replaces itself with the real address. It costs
 * one read — on the way to a page that was going to read that entity anyway.
 */

import type { QueryClient } from "@tanstack/react-query";

import {
  getReadCalendarEventApiV1GGuildIdCalendarEventsEventIdGetQueryKey,
  readCalendarEventApiV1GGuildIdCalendarEventsEventIdGet,
} from "@/api/generated/calendar-events/calendar-events";
import {
  getReadCalendarApiV1GGuildIdCalendarsCalendarIdGetQueryKey,
  readCalendarApiV1GGuildIdCalendarsCalendarIdGet,
} from "@/api/generated/calendars/calendars";
import {
  getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey,
  readCounterGroupApiV1GGuildIdCounterGroupsGroupIdGet,
} from "@/api/generated/counters/counters";
import {
  getReadDashboardApiV1GGuildIdDashboardsDashboardIdGetQueryKey,
  readDashboardApiV1GGuildIdDashboardsDashboardIdGet,
} from "@/api/generated/dashboards/dashboards";
import {
  getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey,
  readDocumentApiV1GGuildIdDocumentsDocumentIdGet,
} from "@/api/generated/documents/documents";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  readProjectApiV1GGuildIdProjectsProjectIdGet,
} from "@/api/generated/projects/projects";
import {
  getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey,
  readQueueApiV1GGuildIdQueuesQueueIdGet,
} from "@/api/generated/queues/queues";
import {
  getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey,
  readTaskApiV1GGuildIdTasksTaskIdGet,
} from "@/api/generated/tasks/tasks";
import { eventRoute, initiativeRoute, taskRoute, toolDetailRoute } from "@/lib/tools";

/**
 * The kinds of thing `/go/{refType}/{id}` can resolve. The six tools are named
 * by their kebab singular (what `toolKebabSingular` produces), plus the two
 * child entities that carry their own ids in links.
 */
export type EntityRefType =
  | "project"
  | "document"
  | "queue"
  | "counter-group"
  | "calendar"
  | "dashboard"
  | "task"
  | "event";

const REF_TYPES = new Set<string>([
  "project",
  "document",
  "queue",
  "counter-group",
  "calendar",
  "dashboard",
  "task",
  "event",
]);

export const isEntityRefType = (value: string): value is EntityRefType => REF_TYPES.has(value);

const STALE_TIME = 30_000;

/**
 * The guild-relative path an entity lives at, or `null` when it can't be
 * resolved — it was deleted, the reader can't see it, or its parent is gone.
 * Callers send `null` to the guild home rather than guessing at an address.
 */
export async function resolveEntityPath(
  queryClient: QueryClient,
  guildId: number,
  refType: string,
  entityId: number
): Promise<string | null> {
  if (!Number.isFinite(entityId) || !isEntityRefType(refType)) return null;

  const fetch = <T>(queryKey: readonly unknown[], queryFn: () => Promise<T>) =>
    queryClient.ensureQueryData({ queryKey, queryFn, staleTime: STALE_TIME });

  try {
    switch (refType) {
      case "project": {
        const project = await fetch(
          getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(guildId, entityId),
          () => readProjectApiV1GGuildIdProjectsProjectIdGet(guildId, entityId)
        );
        return toolDetailRoute(Tool.project, project.initiative_id, entityId);
      }
      case "document": {
        const document = await fetch(
          getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey(guildId, entityId),
          () => readDocumentApiV1GGuildIdDocumentsDocumentIdGet(guildId, entityId)
        );
        return toolDetailRoute(Tool.document, document.initiative_id, entityId);
      }
      case "queue": {
        const queue = await fetch(
          getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey(guildId, entityId),
          () => readQueueApiV1GGuildIdQueuesQueueIdGet(guildId, entityId)
        );
        return toolDetailRoute(Tool.queue, queue.initiative_id, entityId);
      }
      case "counter-group": {
        const group = await fetch(
          getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, entityId),
          () => readCounterGroupApiV1GGuildIdCounterGroupsGroupIdGet(guildId, entityId)
        );
        return toolDetailRoute(Tool.counter_group, group.initiative_id, entityId);
      }
      case "dashboard": {
        const dashboard = await fetch(
          getReadDashboardApiV1GGuildIdDashboardsDashboardIdGetQueryKey(guildId, entityId),
          () => readDashboardApiV1GGuildIdDashboardsDashboardIdGet(guildId, entityId)
        );
        return toolDetailRoute(Tool.dashboard, dashboard.initiative_id, entityId);
      }
      case "calendar": {
        const calendar = await fetch(
          getReadCalendarApiV1GGuildIdCalendarsCalendarIdGetQueryKey(guildId, entityId),
          () => readCalendarApiV1GGuildIdCalendarsCalendarIdGet(guildId, entityId)
        );
        // A null initiative is an app-installed calendar, which keeps a guild
        // address — not a failure to resolve.
        return toolDetailRoute(Tool.calendar, calendar.initiative_id, entityId);
      }
      case "task": {
        const task = await fetch(
          getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey(guildId, entityId),
          () => readTaskApiV1GGuildIdTasksTaskIdGet(guildId, entityId)
        );
        // The embedded project summary usually names the initiative; when the
        // task read omits it, the project itself is the authority.
        const initiativeId =
          task.project?.initiative_id ??
          (
            await fetch(
              getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(guildId, task.project_id),
              () => readProjectApiV1GGuildIdProjectsProjectIdGet(guildId, task.project_id)
            )
          ).initiative_id;
        return taskRoute(initiativeId, task.project_id, entityId);
      }
      case "event": {
        const event = await fetch(
          getReadCalendarEventApiV1GGuildIdCalendarEventsEventIdGetQueryKey(guildId, entityId),
          () => readCalendarEventApiV1GGuildIdCalendarEventsEventIdGet(guildId, entityId)
        );
        return eventRoute(event.initiative_id, event.calendar_id, entityId);
      }
    }
  } catch {
    // Deleted, or the reader can't see it. The caller lands on the guild home.
    return null;
  }
}

/**
 * Rewrite a guild-relative path written before tools were addressed inside
 * their initiative onto the `/go` resolver.
 *
 * Notification rows persist their `target_path`, so links minted by an older
 * build are still arriving. This is a data migration for those rows, not a
 * revival of the old routes — nothing renders at these paths any more.
 */
const LEGACY_TARGETS: Array<[RegExp, (id: string) => string]> = [
  [/^\/tasks\/(\d+)(\/.*)?$/, (id) => `/go/task/${id}`],
  [/^\/projects\/(\d+)(\/.*)?$/, (id) => `/go/project/${id}`],
  [/^\/documents\/(\d+)(\/.*)?$/, (id) => `/go/document/${id}`],
  [/^\/calendar-events\/(\d+)(\/.*)?$/, (id) => `/go/event/${id}`],
  [/^\/initiatives\/(\d+)(\/.*)?$/, (id) => initiativeRoute(Number(id))],
];

/** Guild-relative paths that used to name a list page and no longer exist.
 *  (`/initiatives` among them: that list is part of the guild home now.) */
const LEGACY_LISTS = new Set([
  "/initiatives",
  "/tasks",
  "/projects",
  "/documents",
  "/queues",
  "/dashboards",
  "/counter-groups",
  "/calendars",
  "/calendar",
]);

export function normalizeLegacyTarget(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  for (const [pattern, build] of LEGACY_TARGETS) {
    const match = normalized.match(pattern);
    if (match) return build(match[1]);
  }
  if (LEGACY_LISTS.has(normalized)) return "/";
  return normalized;
}
