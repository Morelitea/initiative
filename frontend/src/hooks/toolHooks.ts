/**
 * The hooks every tool repeats, written once.
 *
 * Nine tools ask the API the same seven questions — how many of me does each
 * initiative hold, list me, read one of me, create, update, delete, share —
 * over endpoints that differ only in their names. Each `use<Tool>s.ts` used to
 * spell all seven out; they are built here from the generated client instead,
 * and that file re-exports them under the names its callers already use.
 *
 * Cache keys come from the generated key builders and invalidation from the
 * `q.*` descriptions in `@/api/query-keys`, so a tool's queries are named in
 * exactly one place however they are reached.
 *
 * `TOOL_HOOKS` below is the table, keyed by `Tool`, and it says tool by tool
 * which of the seven come from here. A hook that genuinely differs — a list
 * that walks every page, a create that also links the new row to a project —
 * is absent from that tool's entry and stays hand-written in its own file,
 * rather than being reached by a flag here.
 *
 * Three questions are asked for EVERY tool, however its hook is written: how
 * many of me per initiative, one page of me in this community, one page of me
 * across all of them. Those three are in the table as query options rather
 * than hooks, because the surfaces that ask them ask every tool at once and
 * hand the lot to `useQueries` — a hook cannot be called in a loop. A tool
 * whose hook is hand-written still declares its options here, so the query is
 * described once and the hand-written hook wraps these rather than repeating
 * the key.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  createCalendarApiV1CGuildIdCalendarsPost,
  deleteCalendarApiV1CGuildIdCalendarsCalendarIdDelete,
  getCalendarCountsByInitiativeApiV1CGuildIdCalendarsCountsByInitiativeGet,
  getGetCalendarCountsByInitiativeApiV1CGuildIdCalendarsCountsByInitiativeGetQueryKey,
  getListCalendarsApiV1CGuildIdCalendarsGetQueryKey,
  getReadCalendarApiV1CGuildIdCalendarsCalendarIdGetQueryKey,
  listCalendarsApiV1CGuildIdCalendarsGet,
  readCalendarApiV1CGuildIdCalendarsCalendarIdGet,
  setCalendarGrantsApiV1CGuildIdCalendarsCalendarIdGrantsPut,
  updateCalendarApiV1CGuildIdCalendarsCalendarIdPatch,
} from "@/api/generated/calendars/calendars";
import {
  createCounterGroupApiV1CGuildIdCounterGroupsPost,
  deleteCounterGroupApiV1CGuildIdCounterGroupsGroupIdDelete,
  getCounterGroupCountsByInitiativeApiV1CGuildIdCounterGroupsCountsByInitiativeGet,
  getGetCounterGroupCountsByInitiativeApiV1CGuildIdCounterGroupsCountsByInitiativeGetQueryKey,
  getListCounterGroupsApiV1CGuildIdCounterGroupsGetQueryKey,
  getReadCounterGroupApiV1CGuildIdCounterGroupsGroupIdGetQueryKey,
  listCounterGroupsApiV1CGuildIdCounterGroupsGet,
  readCounterGroupApiV1CGuildIdCounterGroupsGroupIdGet,
  setCounterGroupGrantsApiV1CGuildIdCounterGroupsGroupIdGrantsPut,
  updateCounterGroupApiV1CGuildIdCounterGroupsGroupIdPatch,
} from "@/api/generated/counters/counters";
import {
  createDashboardApiV1CGuildIdDashboardsPost,
  deleteDashboardApiV1CGuildIdDashboardsDashboardIdDelete,
  getDashboardCountsByInitiativeApiV1CGuildIdDashboardsCountsByInitiativeGet,
  getGetDashboardCountsByInitiativeApiV1CGuildIdDashboardsCountsByInitiativeGetQueryKey,
  getListDashboardsApiV1CGuildIdDashboardsGetQueryKey,
  getReadDashboardApiV1CGuildIdDashboardsDashboardIdGetQueryKey,
  listDashboardsApiV1CGuildIdDashboardsGet,
  readDashboardApiV1CGuildIdDashboardsDashboardIdGet,
  setDashboardGrantsApiV1CGuildIdDashboardsDashboardIdGrantsPut,
  updateDashboardApiV1CGuildIdDashboardsDashboardIdPatch,
} from "@/api/generated/dashboards/dashboards";
import {
  deleteDocumentApiV1CGuildIdDocumentsDocumentIdDelete,
  getDocumentCountsByInitiativeApiV1CGuildIdDocumentsCountsByInitiativeGet,
  getGetDocumentCountsByInitiativeApiV1CGuildIdDocumentsCountsByInitiativeGetQueryKey,
  getListDocumentsApiV1CGuildIdDocumentsGetQueryKey,
  getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey,
  listDocumentsApiV1CGuildIdDocumentsGet,
  readDocumentApiV1CGuildIdDocumentsDocumentIdGet,
  setDocumentGrantsApiV1CGuildIdDocumentsDocumentIdGrantsPut,
} from "@/api/generated/documents/documents";
import {
  createGalleryApiV1CGuildIdGalleriesPost,
  deleteGalleryApiV1CGuildIdGalleriesGalleryIdDelete,
  getGalleryCountsByInitiativeApiV1CGuildIdGalleriesCountsByInitiativeGet,
  getGetGalleryCountsByInitiativeApiV1CGuildIdGalleriesCountsByInitiativeGetQueryKey,
  getListGalleriesApiV1CGuildIdGalleriesGetQueryKey,
  getReadGalleryApiV1CGuildIdGalleriesGalleryIdGetQueryKey,
  listGalleriesApiV1CGuildIdGalleriesGet,
  readGalleryApiV1CGuildIdGalleriesGalleryIdGet,
  setGalleryGrantsApiV1CGuildIdGalleriesGalleryIdGrantsPut,
  updateGalleryApiV1CGuildIdGalleriesGalleryIdPatch,
} from "@/api/generated/galleries/galleries";
import type {
  InitiativeGroupedCountsResponse,
  ListDocumentsApiV1CGuildIdDocumentsGetParams,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getListMyCalendarsApiV1MeCalendarsGetQueryKey,
  getListMyCounterGroupsApiV1MeCounterGroupsGetQueryKey,
  getListMyDashboardsApiV1MeDashboardsGetQueryKey,
  getListMyDocumentsApiV1MeDocumentsGetQueryKey,
  getListMyGalleriesApiV1MeGalleriesGetQueryKey,
  getListMyPostsApiV1MePostsGetQueryKey,
  getListMyProjectsApiV1MeProjectsGetQueryKey,
  getListMyQueuesApiV1MeQueuesGetQueryKey,
  getListMyWikisApiV1MeWikisGetQueryKey,
  listMyCalendarsApiV1MeCalendarsGet,
  listMyCounterGroupsApiV1MeCounterGroupsGet,
  listMyDashboardsApiV1MeDashboardsGet,
  listMyDocumentsApiV1MeDocumentsGet,
  listMyGalleriesApiV1MeGalleriesGet,
  listMyPostsApiV1MePostsGet,
  listMyProjectsApiV1MeProjectsGet,
  listMyQueuesApiV1MeQueuesGet,
  listMyWikisApiV1MeWikisGet,
} from "@/api/generated/my-tools/my-tools";
import {
  createPostApiV1CGuildIdPostsPost,
  deletePostApiV1CGuildIdPostsPostIdDelete,
  getGetPostCountsByInitiativeApiV1CGuildIdPostsCountsByInitiativeGetQueryKey,
  getListPostsApiV1CGuildIdPostsGetQueryKey,
  getPostCountsByInitiativeApiV1CGuildIdPostsCountsByInitiativeGet,
  getReadPostApiV1CGuildIdPostsPostIdGetQueryKey,
  listPostsApiV1CGuildIdPostsGet,
  readPostApiV1CGuildIdPostsPostIdGet,
  setPostGrantsApiV1CGuildIdPostsPostIdGrantsPut,
  updatePostApiV1CGuildIdPostsPostIdPatch,
} from "@/api/generated/posts/posts";
import {
  createProjectApiV1CGuildIdProjectsPost,
  deleteProjectApiV1CGuildIdProjectsProjectIdDelete,
  getGetProjectCountsByInitiativeApiV1CGuildIdProjectsCountsByInitiativeGetQueryKey,
  getListProjectsApiV1CGuildIdProjectsGetQueryKey,
  getProjectCountsByInitiativeApiV1CGuildIdProjectsCountsByInitiativeGet,
  getReadProjectApiV1CGuildIdProjectsProjectIdGetQueryKey,
  listProjectsApiV1CGuildIdProjectsGet,
  readProjectApiV1CGuildIdProjectsProjectIdGet,
  setProjectGrantsApiV1CGuildIdProjectsProjectIdGrantsPut,
} from "@/api/generated/projects/projects";
import {
  createQueueApiV1CGuildIdQueuesPost,
  deleteQueueApiV1CGuildIdQueuesQueueIdDelete,
  getGetQueueCountsByInitiativeApiV1CGuildIdQueuesCountsByInitiativeGetQueryKey,
  getListQueuesApiV1CGuildIdQueuesGetQueryKey,
  getQueueCountsByInitiativeApiV1CGuildIdQueuesCountsByInitiativeGet,
  getReadQueueApiV1CGuildIdQueuesQueueIdGetQueryKey,
  listQueuesApiV1CGuildIdQueuesGet,
  readQueueApiV1CGuildIdQueuesQueueIdGet,
  setQueueGrantsApiV1CGuildIdQueuesQueueIdGrantsPut,
  updateQueueApiV1CGuildIdQueuesQueueIdPatch,
} from "@/api/generated/queues/queues";
import {
  createWikiApiV1CGuildIdWikisPost,
  deleteWikiApiV1CGuildIdWikisWikiIdDelete,
  getGetWikiCountsByInitiativeApiV1CGuildIdWikisCountsByInitiativeGetQueryKey,
  getListWikisApiV1CGuildIdWikisGetQueryKey,
  getReadWikiApiV1CGuildIdWikisWikiIdGetQueryKey,
  getWikiCountsByInitiativeApiV1CGuildIdWikisCountsByInitiativeGet,
  listWikisApiV1CGuildIdWikisGet,
  readWikiApiV1CGuildIdWikisWikiIdGet,
  setWikiGrantsApiV1CGuildIdWikisWikiIdGrantsPut,
  updateWikiApiV1CGuildIdWikisWikiIdPatch,
} from "@/api/generated/wikis/wikis";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** A cache key, as the generated key builders return one. */
type CacheKey = readonly unknown[];

/**
 * The narrowing every tool's guild-wide list understands.
 *
 * The nine endpoints accept far more than this between them — a document has
 * tags and a type, a calendar has a scope — but these are the terms they ALL
 * take, which is what lets one caller drive every tool from one params object.
 * A tool's own list hook keeps its own generated params type and can ask for
 * the rest.
 */
export interface ToolListParams {
  page?: number;
  page_size?: number;
  search?: string | null;
  sort_by?: string | null;
  sort_dir?: string | null;
  archived?: boolean | null;
  initiative_id?: number | null;
}

/**
 * The same, for the cross-guild `/me` twin: no initiative (there is no order
 * across communities to put one in), a set of communities instead, and the
 * "only what I wrote" view.
 */
export interface ToolMyListParams {
  guild_ids?: number[] | null;
  search?: string | null;
  created_by_me?: boolean;
  sort_by?: string | null;
  sort_dir?: string | null;
  page?: number;
  page_size?: number;
}

/**
 * What every tool's list answers with — what a caller can count on before it
 * knows which tool it is holding.
 */
interface ToolListPage {
  items: unknown[];
  total_count: number;
  has_next: boolean;
}

// ── The seven, each built from the endpoints that answer it ──────────────────
// Every builder takes the tool's endpoint record and reads only the fields it
// needs, so a tool that has no standard version of one hook simply leaves those
// fields out of its record and never calls that builder.

/**
 * Visible-entity counts per initiative, for the sidebar badges.
 *
 * Two shapes of the one query: the hook, for a page that wants this tool's
 * counts, and the options behind it, for a caller that wants every tool's at
 * once and hands the lot to `useQueries` — hooks cannot be called in a loop.
 */
const countsHooks = (endpoints: {
  countsKey: (guildId: number) => CacheKey;
  counts: (guildId: number) => Promise<InitiativeGroupedCountsResponse>;
}) => {
  const countsQuery = (guildId: number) => ({
    queryKey: endpoints.countsKey(guildId),
    queryFn: () => endpoints.counts(guildId),
  });
  return { countsQuery };
};

/**
 * One page of the tool's list, in this community and across every one at once.
 *
 * Options rather than hooks, for the same reason `countsQuery` is: the two
 * tables that show one tool at a time ask all nine and hand the lot to
 * `useQueries`. Both are declared for every tool, including the ones whose own
 * list hook is hand-written — those wrap these, so the key and the fetch are
 * written once wherever the list is reached from.
 */
const listQueries = <TList, TMyList, TParams, TMyParams>(endpoints: {
  listKey: (guildId: number, params?: TParams) => CacheKey;
  list: (guildId: number, params?: TParams) => Promise<TList>;
  myListKey: (params?: TMyParams) => CacheKey;
  myList: (params?: TMyParams) => Promise<TMyList>;
}) => ({
  listQuery: (guildId: number, params?: TParams) => ({
    queryKey: endpoints.listKey(guildId, params),
    queryFn: () => endpoints.list(guildId, params),
  }),
  myListQuery: (params?: TMyParams) => ({
    queryKey: endpoints.myListKey(params),
    queryFn: () => endpoints.myList(params),
  }),
});

/**
 * One page of the tool's guild-wide list.
 *
 * `keepPreviousData` keeps the rows on screen while a changed page, search or
 * order is in flight, rather than replacing the table with a loading line on
 * every keystroke.
 */
const listHook = <TList, TParams>(endpoints: {
  listKey: (guildId: number, params?: TParams) => CacheKey;
  list: (guildId: number, params?: TParams) => Promise<TList>;
}) => {
  return (params?: TParams, options?: QueryOpts<TList>) => {
    const guildId = useActiveGuildId();
    return useQuery<TList>({
      queryKey: endpoints.listKey(guildId, params),
      queryFn: () => endpoints.list(guildId, params),
      placeholderData: keepPreviousData,
      ...options,
    });
  };
};

/**
 * One row. `null` for an id the route has not resolved yet, which holds the
 * request rather than firing it at nothing; a caller's own `enabled` narrows
 * further and never widens.
 */
const detailHook = <TRead>(endpoints: {
  detailKey: (guildId: number, id: number) => CacheKey;
  detail: (guildId: number, id: number) => Promise<TRead>;
}) => {
  return (id: number | null, options?: QueryOpts<TRead>) => {
    const guildId = useActiveGuildId();
    const { enabled: userEnabled = true, ...rest } = options ?? {};
    return useQuery<TRead>({
      queryKey: endpoints.detailKey(guildId, id!),
      queryFn: () => endpoints.detail(guildId, id!),
      enabled: id !== null && Number.isFinite(id) && userEnabled,
      ...rest,
    });
  };
};

const createHook = <TRead, TCreate>(
  endpoints: {
    create: (guildId: number, data: TCreate) => Promise<TRead>;
    all: () => Spec;
  },
  errorKey: string
) => {
  return (options?: MutationOpts<TRead, TCreate>) =>
    useGuildMutation<TRead, TCreate>(
      {
        mutationFn: (guildId, data) => endpoints.create(guildId, data),
        invalidate: () => invalidate(endpoints.all()),
        errorKey,
      },
      options
    );
};

interface ToolWriteOptions {
  /**
   * Whether the update seeds the detail cache with what the PATCH answered.
   *
   * The response is the row a refetch would fetch, so seeding it beats leaving
   * the cache on the pre-save copy until the refetch lands. Without it a canvas
   * that drops its local draft the moment a save succeeds renders the *old*
   * server layout for a beat — a dragged widget visibly snaps back to where it
   * came from, then jumps forward again when the refetch arrives.
   */
  seedsDetailOnUpdate?: boolean;
}

const updateHook = <TRead, TUpdate>(
  endpoints: {
    update: (guildId: number, id: number, data: TUpdate) => Promise<TRead>;
    detailKey: (guildId: number, id: number) => CacheKey;
    one: (id: number) => Spec;
    all: () => Spec;
  },
  errorKey: string,
  { seedsDetailOnUpdate = false }: ToolWriteOptions = {}
) => {
  return (id: number, options?: MutationOpts<TRead, TUpdate>) => {
    const guildId = useActiveGuildId();
    return useGuildMutation<TRead, TUpdate>(
      {
        mutationFn: (guild, data) => endpoints.update(guild, id, data),
        invalidate: (updated) => {
          if (seedsDetailOnUpdate) {
            queryClient.setQueryData(endpoints.detailKey(guildId, id), updated);
          }
          return invalidate(endpoints.one(id), endpoints.all());
        },
        errorKey,
      },
      options
    );
  };
};

const deleteHook = (
  endpoints: {
    remove: (guildId: number, id: number) => Promise<void>;
    all: () => Spec;
  },
  errorKey: string
) => {
  return (options?: MutationOpts<void, number>) =>
    useGuildMutation<void, number>(
      {
        mutationFn: (guildId, id) => endpoints.remove(guildId, id),
        invalidate: () => invalidate(endpoints.all()),
        errorKey,
      },
      options
    );
};

/** The whole non-owner sharing state at once (unified resource sharing). */
const grantsHook = <TRead>(
  endpoints: {
    setGrants: (guildId: number, id: number, grants: ResourceGrantSchema[]) => Promise<TRead>;
    one: (id: number) => Spec;
    all: () => Spec;
  },
  errorKey: string
) => {
  return (id: number, options?: MutationOpts<TRead, ResourceGrantSchema[]>) =>
    useGuildMutation<TRead, ResourceGrantSchema[]>(
      {
        mutationFn: (guildId, grants) => endpoints.setGrants(guildId, id, grants),
        invalidate: () => invalidate(endpoints.one(id), endpoints.all()),
        errorKey,
      },
      options
    );
};

/** Everything the generated client offers for a tool with no exceptions. */
interface ToolEndpoints<TRead, TList, TMyList, TCreate, TUpdate, TParams> {
  countsKey: (guildId: number) => CacheKey;
  counts: (guildId: number) => Promise<InitiativeGroupedCountsResponse>;
  listKey: (guildId: number, params?: TParams) => CacheKey;
  list: (guildId: number, params?: TParams) => Promise<TList>;
  myListKey: (params?: ToolMyListParams) => CacheKey;
  myList: (params?: ToolMyListParams) => Promise<TMyList>;
  detailKey: (guildId: number, id: number) => CacheKey;
  detail: (guildId: number, id: number) => Promise<TRead>;
  create: (guildId: number, data: TCreate) => Promise<TRead>;
  update: (guildId: number, id: number, data: TUpdate) => Promise<TRead>;
  remove: (guildId: number, id: number) => Promise<void>;
  setGrants: (guildId: number, id: number, grants: ResourceGrantSchema[]) => Promise<TRead>;
  /** This tool's lists — including the cross-guild `/me` twin, where it has one. */
  all: () => Spec;
  /** One row of it. */
  one: (id: number) => Spec;
}

/** All seven, for a tool whose list and whose four writes are the standard ones. */
const makeToolHooks = <TRead, TList, TMyList, TCreate, TUpdate, TParams>(
  endpoints: ToolEndpoints<TRead, TList, TMyList, TCreate, TUpdate, TParams>,
  errorKey: string,
  options?: ToolWriteOptions
) => ({
  ...countsHooks(endpoints),
  ...listQueries(endpoints),
  useList: listHook(endpoints),
  useDetail: detailHook(endpoints),
  useCreate: createHook(endpoints, errorKey),
  useUpdate: updateHook(endpoints, errorKey, options),
  useDelete: deleteHook(endpoints, errorKey),
  useSetGrants: grantsHook(endpoints, errorKey),
});

// ── One record per tool ──────────────────────────────────────────────────────

const calendarEndpoints = {
  countsKey: getGetCalendarCountsByInitiativeApiV1CGuildIdCalendarsCountsByInitiativeGetQueryKey,
  counts: getCalendarCountsByInitiativeApiV1CGuildIdCalendarsCountsByInitiativeGet,
  listKey: getListCalendarsApiV1CGuildIdCalendarsGetQueryKey,
  list: listCalendarsApiV1CGuildIdCalendarsGet,
  myListKey: getListMyCalendarsApiV1MeCalendarsGetQueryKey,
  myList: listMyCalendarsApiV1MeCalendarsGet,
  detailKey: getReadCalendarApiV1CGuildIdCalendarsCalendarIdGetQueryKey,
  detail: readCalendarApiV1CGuildIdCalendarsCalendarIdGet,
  create: createCalendarApiV1CGuildIdCalendarsPost,
  update: updateCalendarApiV1CGuildIdCalendarsCalendarIdPatch,
  remove: deleteCalendarApiV1CGuildIdCalendarsCalendarIdDelete,
  setGrants: setCalendarGrantsApiV1CGuildIdCalendarsCalendarIdGrantsPut,
  all: q.allCalendars,
  one: q.calendar,
};

const counterGroupEndpoints = {
  countsKey:
    getGetCounterGroupCountsByInitiativeApiV1CGuildIdCounterGroupsCountsByInitiativeGetQueryKey,
  counts: getCounterGroupCountsByInitiativeApiV1CGuildIdCounterGroupsCountsByInitiativeGet,
  listKey: getListCounterGroupsApiV1CGuildIdCounterGroupsGetQueryKey,
  list: listCounterGroupsApiV1CGuildIdCounterGroupsGet,
  myListKey: getListMyCounterGroupsApiV1MeCounterGroupsGetQueryKey,
  myList: listMyCounterGroupsApiV1MeCounterGroupsGet,
  detailKey: getReadCounterGroupApiV1CGuildIdCounterGroupsGroupIdGetQueryKey,
  detail: readCounterGroupApiV1CGuildIdCounterGroupsGroupIdGet,
  create: createCounterGroupApiV1CGuildIdCounterGroupsPost,
  update: updateCounterGroupApiV1CGuildIdCounterGroupsGroupIdPatch,
  remove: deleteCounterGroupApiV1CGuildIdCounterGroupsGroupIdDelete,
  setGrants: setCounterGroupGrantsApiV1CGuildIdCounterGroupsGroupIdGrantsPut,
  all: q.allCounterGroups,
  one: q.counterGroup,
};

const dashboardEndpoints = {
  countsKey: getGetDashboardCountsByInitiativeApiV1CGuildIdDashboardsCountsByInitiativeGetQueryKey,
  counts: getDashboardCountsByInitiativeApiV1CGuildIdDashboardsCountsByInitiativeGet,
  listKey: getListDashboardsApiV1CGuildIdDashboardsGetQueryKey,
  list: listDashboardsApiV1CGuildIdDashboardsGet,
  myListKey: getListMyDashboardsApiV1MeDashboardsGetQueryKey,
  myList: listMyDashboardsApiV1MeDashboardsGet,
  detailKey: getReadDashboardApiV1CGuildIdDashboardsDashboardIdGetQueryKey,
  detail: readDashboardApiV1CGuildIdDashboardsDashboardIdGet,
  create: createDashboardApiV1CGuildIdDashboardsPost,
  update: updateDashboardApiV1CGuildIdDashboardsDashboardIdPatch,
  remove: deleteDashboardApiV1CGuildIdDashboardsDashboardIdDelete,
  setGrants: setDashboardGrantsApiV1CGuildIdDashboardsDashboardIdGrantsPut,
  all: q.allDashboards,
  one: q.dashboard,
};

// Documents have no standard list hook (theirs takes filters no other tool has,
// and keeps its own placeholder rows), create (theirs can also link the new row
// to a project) or update (theirs seeds the cache and refreshes the
// relationship graph) — all three live in `useDocuments.ts`. The list QUERY is
// here like every other tool's, and that hook wraps it.
const documentEndpoints = {
  countsKey: getGetDocumentCountsByInitiativeApiV1CGuildIdDocumentsCountsByInitiativeGetQueryKey,
  counts: getDocumentCountsByInitiativeApiV1CGuildIdDocumentsCountsByInitiativeGet,
  listKey: getListDocumentsApiV1CGuildIdDocumentsGetQueryKey,
  // `page_size: 0` asks for the complete set, which the server serves in
  // windows; this walks them. A positive page size passes straight through.
  list: (guildId: number, params?: ListDocumentsApiV1CGuildIdDocumentsGetParams) =>
    fetchAllPages(listDocumentsApiV1CGuildIdDocumentsGet, guildId, params ?? {}),
  myListKey: getListMyDocumentsApiV1MeDocumentsGetQueryKey,
  myList: listMyDocumentsApiV1MeDocumentsGet,
  detailKey: getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey,
  detail: readDocumentApiV1CGuildIdDocumentsDocumentIdGet,
  remove: deleteDocumentApiV1CGuildIdDocumentsDocumentIdDelete,
  setGrants: setDocumentGrantsApiV1CGuildIdDocumentsDocumentIdGrantsPut,
  all: q.allDocuments,
  one: q.document,
};

const documentHooks = {
  ...countsHooks(documentEndpoints),
  ...listQueries(documentEndpoints),
  useDetail: detailHook(documentEndpoints),
  useDelete: deleteHook(documentEndpoints, "documents:bulk.deleteError"),
  useSetGrants: grantsHook(documentEndpoints, "documents:settings.updateAccessError"),
};

const galleryEndpoints = {
  countsKey: getGetGalleryCountsByInitiativeApiV1CGuildIdGalleriesCountsByInitiativeGetQueryKey,
  counts: getGalleryCountsByInitiativeApiV1CGuildIdGalleriesCountsByInitiativeGet,
  listKey: getListGalleriesApiV1CGuildIdGalleriesGetQueryKey,
  list: listGalleriesApiV1CGuildIdGalleriesGet,
  myListKey: getListMyGalleriesApiV1MeGalleriesGetQueryKey,
  myList: listMyGalleriesApiV1MeGalleriesGet,
  detailKey: getReadGalleryApiV1CGuildIdGalleriesGalleryIdGetQueryKey,
  detail: readGalleryApiV1CGuildIdGalleriesGalleryIdGet,
  create: createGalleryApiV1CGuildIdGalleriesPost,
  update: updateGalleryApiV1CGuildIdGalleriesGalleryIdPatch,
  remove: deleteGalleryApiV1CGuildIdGalleriesGalleryIdDelete,
  setGrants: setGalleryGrantsApiV1CGuildIdGalleriesGalleryIdGrantsPut,
  all: q.allGalleries,
  one: q.gallery,
};

const postEndpoints = {
  countsKey: getGetPostCountsByInitiativeApiV1CGuildIdPostsCountsByInitiativeGetQueryKey,
  counts: getPostCountsByInitiativeApiV1CGuildIdPostsCountsByInitiativeGet,
  listKey: getListPostsApiV1CGuildIdPostsGetQueryKey,
  list: listPostsApiV1CGuildIdPostsGet,
  myListKey: getListMyPostsApiV1MePostsGetQueryKey,
  myList: listMyPostsApiV1MePostsGet,
  detailKey: getReadPostApiV1CGuildIdPostsPostIdGetQueryKey,
  detail: readPostApiV1CGuildIdPostsPostIdGet,
  create: createPostApiV1CGuildIdPostsPost,
  update: updatePostApiV1CGuildIdPostsPostIdPatch,
  remove: deletePostApiV1CGuildIdPostsPostIdDelete,
  setGrants: setPostGrantsApiV1CGuildIdPostsPostIdGrantsPut,
  all: q.allPosts,
  one: q.post,
};

// Projects have no standard list hook (theirs is read straight, without
// placeholder rows, because the status-count queries read only `total_count`)
// and no standard update (theirs names the list alone) — both live in
// `useProjects.ts`. The list QUERY is here like every other tool's, and that
// hook wraps it.
const projectEndpoints = {
  countsKey: getGetProjectCountsByInitiativeApiV1CGuildIdProjectsCountsByInitiativeGetQueryKey,
  counts: getProjectCountsByInitiativeApiV1CGuildIdProjectsCountsByInitiativeGet,
  listKey: getListProjectsApiV1CGuildIdProjectsGetQueryKey,
  list: listProjectsApiV1CGuildIdProjectsGet,
  myListKey: getListMyProjectsApiV1MeProjectsGetQueryKey,
  myList: listMyProjectsApiV1MeProjectsGet,
  detailKey: getReadProjectApiV1CGuildIdProjectsProjectIdGetQueryKey,
  detail: readProjectApiV1CGuildIdProjectsProjectIdGet,
  create: createProjectApiV1CGuildIdProjectsPost,
  remove: deleteProjectApiV1CGuildIdProjectsProjectIdDelete,
  setGrants: setProjectGrantsApiV1CGuildIdProjectsProjectIdGrantsPut,
  all: q.allProjects,
  one: q.project,
};

const projectHooks = {
  ...countsHooks(projectEndpoints),
  ...listQueries(projectEndpoints),
  useDetail: detailHook(projectEndpoints),
  useCreate: createHook(projectEndpoints, "projects:createDialog.createError"),
  useDelete: deleteHook(projectEndpoints, "projects:detail.loadError"),
  useSetGrants: grantsHook(projectEndpoints, "projects:settings.access.updateError"),
};

const queueEndpoints = {
  countsKey: getGetQueueCountsByInitiativeApiV1CGuildIdQueuesCountsByInitiativeGetQueryKey,
  counts: getQueueCountsByInitiativeApiV1CGuildIdQueuesCountsByInitiativeGet,
  listKey: getListQueuesApiV1CGuildIdQueuesGetQueryKey,
  list: listQueuesApiV1CGuildIdQueuesGet,
  myListKey: getListMyQueuesApiV1MeQueuesGetQueryKey,
  myList: listMyQueuesApiV1MeQueuesGet,
  detailKey: getReadQueueApiV1CGuildIdQueuesQueueIdGetQueryKey,
  detail: readQueueApiV1CGuildIdQueuesQueueIdGet,
  create: createQueueApiV1CGuildIdQueuesPost,
  update: updateQueueApiV1CGuildIdQueuesQueueIdPatch,
  remove: deleteQueueApiV1CGuildIdQueuesQueueIdDelete,
  setGrants: setQueueGrantsApiV1CGuildIdQueuesQueueIdGrantsPut,
  all: q.allQueues,
  one: q.queue,
};

const wikiEndpoints = {
  countsKey: getGetWikiCountsByInitiativeApiV1CGuildIdWikisCountsByInitiativeGetQueryKey,
  counts: getWikiCountsByInitiativeApiV1CGuildIdWikisCountsByInitiativeGet,
  listKey: getListWikisApiV1CGuildIdWikisGetQueryKey,
  list: listWikisApiV1CGuildIdWikisGet,
  myListKey: getListMyWikisApiV1MeWikisGetQueryKey,
  myList: listMyWikisApiV1MeWikisGet,
  detailKey: getReadWikiApiV1CGuildIdWikisWikiIdGetQueryKey,
  detail: readWikiApiV1CGuildIdWikisWikiIdGet,
  create: createWikiApiV1CGuildIdWikisPost,
  update: updateWikiApiV1CGuildIdWikisWikiIdPatch,
  remove: deleteWikiApiV1CGuildIdWikisWikiIdDelete,
  setGrants: setWikiGrantsApiV1CGuildIdWikisWikiIdGrantsPut,
  all: q.allWikis,
  one: q.wiki,
};

/**
 * What every tool's entry carries, whatever else it has. The cross-tool loops
 * read this and nothing more, and `Record<Tool, …>` means a new `Tool` member
 * fails to compile here until it has them.
 *
 * The two list entries are stated in the common terms — a tool's own params
 * type is richer, and its own hook still takes that — so the constraint below
 * is also the check that every tool's list really does accept the narrowing
 * one caller drives all nine with.
 */
interface ToolQueries {
  countsQuery: (guildId: number) => {
    queryKey: CacheKey;
    queryFn: () => Promise<InitiativeGroupedCountsResponse>;
  };
  listQuery: (
    guildId: number,
    params?: ToolListParams
  ) => { queryKey: CacheKey; queryFn: () => Promise<ToolListPage> };
  myListQuery: (params?: ToolMyListParams) => {
    queryKey: CacheKey;
    queryFn: () => Promise<ToolListPage>;
  };
}

/**
 * Which of the seven each tool takes from here.
 *
 * A tool listed with `makeToolHooks` takes all seven; one written out takes the
 * ones it names and keeps the rest hand-written, for the reason stated above
 * its endpoint record.
 */
export const TOOL_HOOKS = {
  [Tool.project]: projectHooks,
  [Tool.document]: documentHooks,
  [Tool.queue]: makeToolHooks(queueEndpoints, "queues:error"),
  [Tool.counter_group]: makeToolHooks(counterGroupEndpoints, "counterGroups:error"),
  [Tool.calendar]: makeToolHooks(calendarEndpoints, "calendars:error"),
  [Tool.dashboard]: makeToolHooks(dashboardEndpoints, "dashboards:error", {
    seedsDetailOnUpdate: true,
  }),
  [Tool.post]: makeToolHooks(postEndpoints, "posts:error", { seedsDetailOnUpdate: true }),
  [Tool.gallery]: makeToolHooks(galleryEndpoints, "galleries:error", {
    seedsDetailOnUpdate: true,
  }),
  [Tool.wiki]: makeToolHooks(wikiEndpoints, "wikis:error"),
} satisfies Record<Tool, ToolQueries>;
