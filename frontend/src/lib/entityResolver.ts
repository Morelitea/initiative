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
  getReadCalendarEventApiV1CGuildIdCalendarEventsEventIdGetQueryKey,
  readCalendarEventApiV1CGuildIdCalendarEventsEventIdGet,
} from "@/api/generated/calendar-events/calendar-events";
import {
  getReadCalendarApiV1CGuildIdCalendarsCalendarIdGetQueryKey,
  readCalendarApiV1CGuildIdCalendarsCalendarIdGet,
} from "@/api/generated/calendars/calendars";
import {
  getReadCounterGroupApiV1CGuildIdCounterGroupsGroupIdGetQueryKey,
  readCounterGroupApiV1CGuildIdCounterGroupsGroupIdGet,
} from "@/api/generated/counters/counters";
import {
  getReadDashboardApiV1CGuildIdDashboardsDashboardIdGetQueryKey,
  readDashboardApiV1CGuildIdDashboardsDashboardIdGet,
} from "@/api/generated/dashboards/dashboards";
import {
  getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey,
  readDocumentApiV1CGuildIdDocumentsDocumentIdGet,
} from "@/api/generated/documents/documents";
import {
  getReadGalleryApiV1CGuildIdGalleriesGalleryIdGetQueryKey,
  readGalleryApiV1CGuildIdGalleriesGalleryIdGet,
} from "@/api/generated/galleries/galleries";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadPostApiV1CGuildIdPostsPostIdGetQueryKey,
  readPostApiV1CGuildIdPostsPostIdGet,
} from "@/api/generated/posts/posts";
import {
  getReadProjectApiV1CGuildIdProjectsProjectIdGetQueryKey,
  readProjectApiV1CGuildIdProjectsProjectIdGet,
} from "@/api/generated/projects/projects";
import {
  getReadQueueApiV1CGuildIdQueuesQueueIdGetQueryKey,
  readQueueApiV1CGuildIdQueuesQueueIdGet,
} from "@/api/generated/queues/queues";
import {
  getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey,
  readTaskApiV1CGuildIdTasksTaskIdGet,
} from "@/api/generated/tasks/tasks";
import {
  getReadWikiApiV1CGuildIdWikisWikiIdGetQueryKey,
  getReadWikiPageByIdApiV1CGuildIdWikiPagesPageIdGetQueryKey,
  readWikiApiV1CGuildIdWikisWikiIdGet,
  readWikiPageByIdApiV1CGuildIdWikiPagesPageIdGet,
} from "@/api/generated/wikis/wikis";
import {
  eventRoute,
  initiativeRoute,
  type PARENT_TOOL,
  TOOLS,
  taskRoute,
  toolDetailRoute,
  toolKebabSingular,
  wikiPageRoute,
} from "@/lib/tools";

const STALE_TIME = 30_000;

/** Reads one row through the query cache, so the page the resolver lands on
 *  finds it already there. */
type Read = <T>(queryKey: readonly unknown[], queryFn: () => Promise<T>) => Promise<T>;

/** How each tool's row is read by its id. Keyed by the whole `Tool` enum, so a
 *  tool without a reader does not compile. */
const TOOL_READS: Record<
  Tool,
  {
    key: (guildId: number, id: number) => readonly unknown[];
    read: (guildId: number, id: number) => Promise<{ initiative_id?: number | null }>;
  }
> = {
  [Tool.project]: {
    key: getReadProjectApiV1CGuildIdProjectsProjectIdGetQueryKey,
    read: readProjectApiV1CGuildIdProjectsProjectIdGet,
  },
  [Tool.document]: {
    key: getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey,
    read: readDocumentApiV1CGuildIdDocumentsDocumentIdGet,
  },
  [Tool.queue]: {
    key: getReadQueueApiV1CGuildIdQueuesQueueIdGetQueryKey,
    read: readQueueApiV1CGuildIdQueuesQueueIdGet,
  },
  [Tool.counter_group]: {
    key: getReadCounterGroupApiV1CGuildIdCounterGroupsGroupIdGetQueryKey,
    read: readCounterGroupApiV1CGuildIdCounterGroupsGroupIdGet,
  },
  [Tool.calendar]: {
    key: getReadCalendarApiV1CGuildIdCalendarsCalendarIdGetQueryKey,
    read: readCalendarApiV1CGuildIdCalendarsCalendarIdGet,
  },
  [Tool.dashboard]: {
    key: getReadDashboardApiV1CGuildIdDashboardsDashboardIdGetQueryKey,
    read: readDashboardApiV1CGuildIdDashboardsDashboardIdGet,
  },
  [Tool.post]: {
    key: getReadPostApiV1CGuildIdPostsPostIdGetQueryKey,
    read: readPostApiV1CGuildIdPostsPostIdGet,
  },
  [Tool.gallery]: {
    key: getReadGalleryApiV1CGuildIdGalleriesGalleryIdGetQueryKey,
    read: readGalleryApiV1CGuildIdGalleriesGalleryIdGet,
  },
  [Tool.wiki]: {
    key: getReadWikiApiV1CGuildIdWikisWikiIdGetQueryKey,
    read: readWikiApiV1CGuildIdWikisWikiIdGet,
  },
};

/** The initiative a tool row lives in. `null` is a guild-level row (an
 *  app-installed calendar), which keeps a guild address — not a failure. */
const toolInitiative = async (
  read: Read,
  guildId: number,
  tool: Tool,
  id: number
): Promise<number | null> => {
  const { key, read: readRow } = TOOL_READS[tool];
  return (await read(key(guildId, id), () => readRow(guildId, id))).initiative_id ?? null;
};

type Resolve = (read: Read, guildId: number, id: number) => Promise<string>;

/**
 * The kinds that live inside a tool and can be read by their own id, keyed by
 * the child-kind registry ({@link PARENT_TOOL}). A counter, a queue item and a
 * picture have no read by id alone, so a link never names one.
 */
const CHILD_RESOLVERS: Partial<Record<keyof typeof PARENT_TOOL, Resolve>> = {
  task: async (read, guildId, id) => {
    const task = await read(getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey(guildId, id), () =>
      readTaskApiV1CGuildIdTasksTaskIdGet(guildId, id)
    );
    // The embedded project summary usually names the initiative; when the
    // task read omits it, the project itself is the authority.
    const initiativeId =
      task.project?.initiative_id ??
      (await toolInitiative(read, guildId, Tool.project, task.project_id));
    return taskRoute(initiativeId, task.project_id, id);
  },
  calendar_event: async (read, guildId, id) => {
    const event = await read(
      getReadCalendarEventApiV1CGuildIdCalendarEventsEventIdGetQueryKey(guildId, id),
      () => readCalendarEventApiV1CGuildIdCalendarEventsEventIdGet(guildId, id)
    );
    return eventRoute(event.initiative_id, event.calendar_id, id);
  },
  wiki_page: async (read, guildId, id) => {
    const page = await read(
      getReadWikiPageByIdApiV1CGuildIdWikiPagesPageIdGetQueryKey(guildId, id),
      () => readWikiPageByIdApiV1CGuildIdWikiPagesPageIdGet(guildId, id)
    );
    const initiativeId = await toolInitiative(read, guildId, Tool.wiki, page.wiki_id);
    return wikiPageRoute(initiativeId, page.wiki_id, id);
  },
};

/**
 * What `/go/{refType}/{id}` can resolve, by ref type: every tool and every
 * child kind above, each named by its kebab singular (`counter-group`,
 * `calendar-event`). Derived from the tool registry and the child kinds, so a
 * new tool is addressable here the day it exists.
 */
const RESOLVERS = new Map<string, Resolve>([
  ...TOOLS.map((tool): [string, Resolve] => [
    toolKebabSingular(tool),
    async (read, guildId, id) =>
      toolDetailRoute(tool, await toolInitiative(read, guildId, tool, id), id),
  ]),
  ...Object.entries(CHILD_RESOLVERS).map(([kind, resolve]): [string, Resolve] => [
    kind.replaceAll("_", "-"),
    resolve as Resolve,
  ]),
]);

export const isEntityRefType = (value: string): boolean => RESOLVERS.has(value);

export const isSearchEntityType = (value: string): value is SearchEntityType =>
  Object.hasOwn(SearchEntityType, value);

/**
 * The ref type addressing an entity of a given kind — its kebab singular — or
 * `null` for a kind that has no address of its own (a counter, a queue item, a
 * tag).
 */
export const entityRefTypeFor = (type: SearchEntityType): string | null => {
  const kebab = type.replaceAll("_", "-");
  return isEntityRefType(kebab) ? kebab : null;
};

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
  const resolve = RESOLVERS.get(refType);
  if (!Number.isFinite(entityId) || !resolve) return null;

  const read = <T>(queryKey: readonly unknown[], queryFn: () => Promise<T>) =>
    queryClient.ensureQueryData({ queryKey, queryFn, staleTime: STALE_TIME });

  try {
    return await resolve(read, guildId, entityId);
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
  [/^\/calendar-events\/(\d+)(\/.*)?$/, (id) => `/go/calendar-event/${id}`],
  // A calendar event's ref type was `event` before every ref type became its
  // kind's kebab singular.
  [/^\/go\/event\/(\d+)$/, (id) => `/go/calendar-event/${id}`],
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

/**
 * App-level (guild-less) paths that a notification may still name.
 *
 * `/settings/profile` never existed as a route — your account lives under
 * `/profile`. Notification rows persist the path they were written with, so
 * the ones already sent have to be rewritten on the way out; the server no
 * longer mints it.
 */
const LEGACY_APP_TARGETS = new Map([
  ["/settings/profile", "/profile/account"],
  ["/settings/account", "/profile/account"],
]);

/** As {@link normalizeLegacyTarget}, for a path that names no guild. */
export function normalizeAppTarget(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return LEGACY_APP_TARGETS.get(normalized) ?? normalized;
}

export function normalizeLegacyTarget(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  for (const [pattern, build] of LEGACY_TARGETS) {
    const match = normalized.match(pattern);
    if (match) return build(match[1]);
  }
  if (LEGACY_LISTS.has(normalized)) return "/";
  return normalized;
}
