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
  createCalendarApiV1GGuildIdCalendarsPost,
  deleteCalendarApiV1GGuildIdCalendarsCalendarIdDelete,
  getCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGet,
  getGetCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGetQueryKey,
  getListCalendarsApiV1GGuildIdCalendarsGetQueryKey,
  getReadCalendarApiV1GGuildIdCalendarsCalendarIdGetQueryKey,
  listCalendarsApiV1GGuildIdCalendarsGet,
  readCalendarApiV1GGuildIdCalendarsCalendarIdGet,
  setCalendarGrantsApiV1GGuildIdCalendarsCalendarIdGrantsPut,
  updateCalendarApiV1GGuildIdCalendarsCalendarIdPatch,
} from "@/api/generated/calendars/calendars";
import {
  createCounterGroupApiV1GGuildIdCounterGroupsPost,
  deleteCounterGroupApiV1GGuildIdCounterGroupsGroupIdDelete,
  getCounterGroupCountsByInitiativeApiV1GGuildIdCounterGroupsCountsByInitiativeGet,
  getGetCounterGroupCountsByInitiativeApiV1GGuildIdCounterGroupsCountsByInitiativeGetQueryKey,
  getListCounterGroupsApiV1GGuildIdCounterGroupsGetQueryKey,
  getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey,
  listCounterGroupsApiV1GGuildIdCounterGroupsGet,
  readCounterGroupApiV1GGuildIdCounterGroupsGroupIdGet,
  setCounterGroupGrantsApiV1GGuildIdCounterGroupsGroupIdGrantsPut,
  updateCounterGroupApiV1GGuildIdCounterGroupsGroupIdPatch,
} from "@/api/generated/counters/counters";
import {
  createDashboardApiV1GGuildIdDashboardsPost,
  deleteDashboardApiV1GGuildIdDashboardsDashboardIdDelete,
  getDashboardCountsByInitiativeApiV1GGuildIdDashboardsCountsByInitiativeGet,
  getGetDashboardCountsByInitiativeApiV1GGuildIdDashboardsCountsByInitiativeGetQueryKey,
  getListDashboardsApiV1GGuildIdDashboardsGetQueryKey,
  getReadDashboardApiV1GGuildIdDashboardsDashboardIdGetQueryKey,
  listDashboardsApiV1GGuildIdDashboardsGet,
  readDashboardApiV1GGuildIdDashboardsDashboardIdGet,
  setDashboardGrantsApiV1GGuildIdDashboardsDashboardIdGrantsPut,
  updateDashboardApiV1GGuildIdDashboardsDashboardIdPatch,
} from "@/api/generated/dashboards/dashboards";
import {
  deleteDocumentApiV1GGuildIdDocumentsDocumentIdDelete,
  getDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGet,
  getGetDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGetQueryKey,
  getListDocumentsApiV1GGuildIdDocumentsGetQueryKey,
  getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey,
  listDocumentsApiV1GGuildIdDocumentsGet,
  readDocumentApiV1GGuildIdDocumentsDocumentIdGet,
  setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut,
} from "@/api/generated/documents/documents";
import {
  createGalleryApiV1GGuildIdGalleriesPost,
  deleteGalleryApiV1GGuildIdGalleriesGalleryIdDelete,
  getGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGet,
  getGetGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGetQueryKey,
  getListGalleriesApiV1GGuildIdGalleriesGetQueryKey,
  getReadGalleryApiV1GGuildIdGalleriesGalleryIdGetQueryKey,
  listGalleriesApiV1GGuildIdGalleriesGet,
  readGalleryApiV1GGuildIdGalleriesGalleryIdGet,
  setGalleryGrantsApiV1GGuildIdGalleriesGalleryIdGrantsPut,
  updateGalleryApiV1GGuildIdGalleriesGalleryIdPatch,
} from "@/api/generated/galleries/galleries";
import type {
  InitiativeGroupedCountsResponse,
  ListDocumentsApiV1GGuildIdDocumentsGetParams,
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
  createPostApiV1GGuildIdPostsPost,
  deletePostApiV1GGuildIdPostsPostIdDelete,
  getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey,
  getListPostsApiV1GGuildIdPostsGetQueryKey,
  getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet,
  getReadPostApiV1GGuildIdPostsPostIdGetQueryKey,
  listPostsApiV1GGuildIdPostsGet,
  readPostApiV1GGuildIdPostsPostIdGet,
  setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut,
  updatePostApiV1GGuildIdPostsPostIdPatch,
} from "@/api/generated/posts/posts";
import {
  createProjectApiV1GGuildIdProjectsPost,
  deleteProjectApiV1GGuildIdProjectsProjectIdDelete,
  getGetProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGetQueryKey,
  getListProjectsApiV1GGuildIdProjectsGetQueryKey,
  getProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGet,
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  listProjectsApiV1GGuildIdProjectsGet,
  readProjectApiV1GGuildIdProjectsProjectIdGet,
  setProjectGrantsApiV1GGuildIdProjectsProjectIdGrantsPut,
} from "@/api/generated/projects/projects";
import {
  createQueueApiV1GGuildIdQueuesPost,
  deleteQueueApiV1GGuildIdQueuesQueueIdDelete,
  getGetQueueCountsByInitiativeApiV1GGuildIdQueuesCountsByInitiativeGetQueryKey,
  getListQueuesApiV1GGuildIdQueuesGetQueryKey,
  getQueueCountsByInitiativeApiV1GGuildIdQueuesCountsByInitiativeGet,
  getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey,
  listQueuesApiV1GGuildIdQueuesGet,
  readQueueApiV1GGuildIdQueuesQueueIdGet,
  setQueueGrantsApiV1GGuildIdQueuesQueueIdGrantsPut,
  updateQueueApiV1GGuildIdQueuesQueueIdPatch,
} from "@/api/generated/queues/queues";
import {
  createWikiApiV1GGuildIdWikisPost,
  deleteWikiApiV1GGuildIdWikisWikiIdDelete,
  getGetWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGetQueryKey,
  getListWikisApiV1GGuildIdWikisGetQueryKey,
  getReadWikiApiV1GGuildIdWikisWikiIdGetQueryKey,
  getWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGet,
  listWikisApiV1GGuildIdWikisGet,
  readWikiApiV1GGuildIdWikisWikiIdGet,
  setWikiGrantsApiV1GGuildIdWikisWikiIdGrantsPut,
  updateWikiApiV1GGuildIdWikisWikiIdPatch,
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
  countsKey: getGetCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGetQueryKey,
  counts: getCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGet,
  listKey: getListCalendarsApiV1GGuildIdCalendarsGetQueryKey,
  list: listCalendarsApiV1GGuildIdCalendarsGet,
  myListKey: getListMyCalendarsApiV1MeCalendarsGetQueryKey,
  myList: listMyCalendarsApiV1MeCalendarsGet,
  detailKey: getReadCalendarApiV1GGuildIdCalendarsCalendarIdGetQueryKey,
  detail: readCalendarApiV1GGuildIdCalendarsCalendarIdGet,
  create: createCalendarApiV1GGuildIdCalendarsPost,
  update: updateCalendarApiV1GGuildIdCalendarsCalendarIdPatch,
  remove: deleteCalendarApiV1GGuildIdCalendarsCalendarIdDelete,
  setGrants: setCalendarGrantsApiV1GGuildIdCalendarsCalendarIdGrantsPut,
  all: q.allCalendars,
  one: q.calendar,
};

const counterGroupEndpoints = {
  countsKey:
    getGetCounterGroupCountsByInitiativeApiV1GGuildIdCounterGroupsCountsByInitiativeGetQueryKey,
  counts: getCounterGroupCountsByInitiativeApiV1GGuildIdCounterGroupsCountsByInitiativeGet,
  listKey: getListCounterGroupsApiV1GGuildIdCounterGroupsGetQueryKey,
  list: listCounterGroupsApiV1GGuildIdCounterGroupsGet,
  myListKey: getListMyCounterGroupsApiV1MeCounterGroupsGetQueryKey,
  myList: listMyCounterGroupsApiV1MeCounterGroupsGet,
  detailKey: getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey,
  detail: readCounterGroupApiV1GGuildIdCounterGroupsGroupIdGet,
  create: createCounterGroupApiV1GGuildIdCounterGroupsPost,
  update: updateCounterGroupApiV1GGuildIdCounterGroupsGroupIdPatch,
  remove: deleteCounterGroupApiV1GGuildIdCounterGroupsGroupIdDelete,
  setGrants: setCounterGroupGrantsApiV1GGuildIdCounterGroupsGroupIdGrantsPut,
  all: q.allCounterGroups,
  one: q.counterGroup,
};

const dashboardEndpoints = {
  countsKey: getGetDashboardCountsByInitiativeApiV1GGuildIdDashboardsCountsByInitiativeGetQueryKey,
  counts: getDashboardCountsByInitiativeApiV1GGuildIdDashboardsCountsByInitiativeGet,
  listKey: getListDashboardsApiV1GGuildIdDashboardsGetQueryKey,
  list: listDashboardsApiV1GGuildIdDashboardsGet,
  myListKey: getListMyDashboardsApiV1MeDashboardsGetQueryKey,
  myList: listMyDashboardsApiV1MeDashboardsGet,
  detailKey: getReadDashboardApiV1GGuildIdDashboardsDashboardIdGetQueryKey,
  detail: readDashboardApiV1GGuildIdDashboardsDashboardIdGet,
  create: createDashboardApiV1GGuildIdDashboardsPost,
  update: updateDashboardApiV1GGuildIdDashboardsDashboardIdPatch,
  remove: deleteDashboardApiV1GGuildIdDashboardsDashboardIdDelete,
  setGrants: setDashboardGrantsApiV1GGuildIdDashboardsDashboardIdGrantsPut,
  all: q.allDashboards,
  one: q.dashboard,
};

// Documents have no standard list hook (theirs takes filters no other tool has,
// and keeps its own placeholder rows), create (theirs can also link the new row
// to a project) or update (theirs seeds the cache and refreshes the
// relationship graph) — all three live in `useDocuments.ts`. The list QUERY is
// here like every other tool's, and that hook wraps it.
const documentEndpoints = {
  countsKey: getGetDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGetQueryKey,
  counts: getDocumentCountsByInitiativeApiV1GGuildIdDocumentsCountsByInitiativeGet,
  listKey: getListDocumentsApiV1GGuildIdDocumentsGetQueryKey,
  // `page_size: 0` asks for the complete set, which the server serves in
  // windows; this walks them. A positive page size passes straight through.
  list: (guildId: number, params?: ListDocumentsApiV1GGuildIdDocumentsGetParams) =>
    fetchAllPages(listDocumentsApiV1GGuildIdDocumentsGet, guildId, params ?? {}),
  myListKey: getListMyDocumentsApiV1MeDocumentsGetQueryKey,
  myList: listMyDocumentsApiV1MeDocumentsGet,
  detailKey: getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey,
  detail: readDocumentApiV1GGuildIdDocumentsDocumentIdGet,
  remove: deleteDocumentApiV1GGuildIdDocumentsDocumentIdDelete,
  setGrants: setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut,
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
  countsKey: getGetGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGetQueryKey,
  counts: getGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGet,
  listKey: getListGalleriesApiV1GGuildIdGalleriesGetQueryKey,
  list: listGalleriesApiV1GGuildIdGalleriesGet,
  myListKey: getListMyGalleriesApiV1MeGalleriesGetQueryKey,
  myList: listMyGalleriesApiV1MeGalleriesGet,
  detailKey: getReadGalleryApiV1GGuildIdGalleriesGalleryIdGetQueryKey,
  detail: readGalleryApiV1GGuildIdGalleriesGalleryIdGet,
  create: createGalleryApiV1GGuildIdGalleriesPost,
  update: updateGalleryApiV1GGuildIdGalleriesGalleryIdPatch,
  remove: deleteGalleryApiV1GGuildIdGalleriesGalleryIdDelete,
  setGrants: setGalleryGrantsApiV1GGuildIdGalleriesGalleryIdGrantsPut,
  all: q.allGalleries,
  one: q.gallery,
};

const postEndpoints = {
  countsKey: getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey,
  counts: getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet,
  listKey: getListPostsApiV1GGuildIdPostsGetQueryKey,
  list: listPostsApiV1GGuildIdPostsGet,
  myListKey: getListMyPostsApiV1MePostsGetQueryKey,
  myList: listMyPostsApiV1MePostsGet,
  detailKey: getReadPostApiV1GGuildIdPostsPostIdGetQueryKey,
  detail: readPostApiV1GGuildIdPostsPostIdGet,
  create: createPostApiV1GGuildIdPostsPost,
  update: updatePostApiV1GGuildIdPostsPostIdPatch,
  remove: deletePostApiV1GGuildIdPostsPostIdDelete,
  setGrants: setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut,
  all: q.allPosts,
  one: q.post,
};

// Projects have no standard list hook (theirs is read straight, without
// placeholder rows, because the status-count queries read only `total_count`)
// and no standard update (theirs names the list alone) — both live in
// `useProjects.ts`. The list QUERY is here like every other tool's, and that
// hook wraps it.
const projectEndpoints = {
  countsKey: getGetProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGetQueryKey,
  counts: getProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGet,
  listKey: getListProjectsApiV1GGuildIdProjectsGetQueryKey,
  list: listProjectsApiV1GGuildIdProjectsGet,
  myListKey: getListMyProjectsApiV1MeProjectsGetQueryKey,
  myList: listMyProjectsApiV1MeProjectsGet,
  detailKey: getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  detail: readProjectApiV1GGuildIdProjectsProjectIdGet,
  create: createProjectApiV1GGuildIdProjectsPost,
  remove: deleteProjectApiV1GGuildIdProjectsProjectIdDelete,
  setGrants: setProjectGrantsApiV1GGuildIdProjectsProjectIdGrantsPut,
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
  countsKey: getGetQueueCountsByInitiativeApiV1GGuildIdQueuesCountsByInitiativeGetQueryKey,
  counts: getQueueCountsByInitiativeApiV1GGuildIdQueuesCountsByInitiativeGet,
  listKey: getListQueuesApiV1GGuildIdQueuesGetQueryKey,
  list: listQueuesApiV1GGuildIdQueuesGet,
  myListKey: getListMyQueuesApiV1MeQueuesGetQueryKey,
  myList: listMyQueuesApiV1MeQueuesGet,
  detailKey: getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey,
  detail: readQueueApiV1GGuildIdQueuesQueueIdGet,
  create: createQueueApiV1GGuildIdQueuesPost,
  update: updateQueueApiV1GGuildIdQueuesQueueIdPatch,
  remove: deleteQueueApiV1GGuildIdQueuesQueueIdDelete,
  setGrants: setQueueGrantsApiV1GGuildIdQueuesQueueIdGrantsPut,
  all: q.allQueues,
  one: q.queue,
};

const wikiEndpoints = {
  countsKey: getGetWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGetQueryKey,
  counts: getWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGet,
  listKey: getListWikisApiV1GGuildIdWikisGetQueryKey,
  list: listWikisApiV1GGuildIdWikisGet,
  myListKey: getListMyWikisApiV1MeWikisGetQueryKey,
  myList: listMyWikisApiV1MeWikisGet,
  detailKey: getReadWikiApiV1GGuildIdWikisWikiIdGetQueryKey,
  detail: readWikiApiV1GGuildIdWikisWikiIdGet,
  create: createWikiApiV1GGuildIdWikisPost,
  update: updateWikiApiV1GGuildIdWikisWikiIdPatch,
  remove: deleteWikiApiV1GGuildIdWikisWikiIdDelete,
  setGrants: setWikiGrantsApiV1GGuildIdWikisWikiIdGrantsPut,
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
