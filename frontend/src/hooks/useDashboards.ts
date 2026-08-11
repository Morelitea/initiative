import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  createDashboardApiV1GGuildIdDashboardsPost,
  deleteDashboardApiV1GGuildIdDashboardsDashboardIdDelete,
  getListDashboardsApiV1GGuildIdDashboardsGetQueryKey,
  getReadDashboardApiV1GGuildIdDashboardsDashboardIdGetQueryKey,
  getReadWidgetCatalogApiV1GGuildIdDashboardsWidgetCatalogGetQueryKey,
  listDashboardsApiV1GGuildIdDashboardsGet,
  readDashboardApiV1GGuildIdDashboardsDashboardIdGet,
  readWidgetCatalogApiV1GGuildIdDashboardsWidgetCatalogGet,
  setDashboardGrantsApiV1GGuildIdDashboardsDashboardIdGrantsPut,
  updateDashboardApiV1GGuildIdDashboardsDashboardIdPatch,
} from "@/api/generated/dashboards/dashboards";
import type {
  DashboardCreate,
  DashboardListResponse,
  DashboardRead,
  DashboardUpdate,
  ListDashboardsApiV1GGuildIdDashboardsGetParams,
  ResourceGrantSchema,
  WidgetCatalog,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllDashboards, invalidateDashboard } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useDashboardsList = (
  params?: ListDashboardsApiV1GGuildIdDashboardsGetParams,
  options?: QueryOpts<DashboardListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<DashboardListResponse>({
    queryKey: getListDashboardsApiV1GGuildIdDashboardsGetQueryKey(guildId, params),
    queryFn: () => listDashboardsApiV1GGuildIdDashboardsGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useDashboard = (dashboardId: number | null, options?: QueryOpts<DashboardRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<DashboardRead>({
    queryKey: getReadDashboardApiV1GGuildIdDashboardsDashboardIdGetQueryKey(guildId, dashboardId!),
    queryFn: () => readDashboardApiV1GGuildIdDashboardsDashboardIdGet(guildId, dashboardId!),
    enabled: dashboardId !== null && Number.isFinite(dashboardId) && userEnabled,
    ...rest,
  });
};

/**
 * The widget vocabulary this build supports — size floors, bindable sources,
 * and options per primitive, plus the named presets.
 *
 * Served rather than duplicated: the backend's ``WIDGET_SPECS`` is the authority
 * on which widgets exist and what each may bind to, so the palette and the
 * canvas read it from here instead of carrying a second copy. Static for the
 * life of a deployment, hence the long stale time.
 */
export const useWidgetCatalog = (options?: QueryOpts<WidgetCatalog>) => {
  const guildId = useActiveGuildId();
  return useQuery<WidgetCatalog>({
    queryKey: getReadWidgetCatalogApiV1GGuildIdDashboardsWidgetCatalogGetQueryKey(guildId),
    queryFn: () => readWidgetCatalogApiV1GGuildIdDashboardsWidgetCatalogGet(guildId),
    staleTime: Number.POSITIVE_INFINITY,
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateDashboardAndList = (dashboardId: number) =>
  Promise.all([invalidateDashboard(dashboardId), invalidateAllDashboards()]);

export const useCreateDashboard = (options?: MutationOpts<DashboardRead, DashboardCreate>) =>
  useGuildMutation<DashboardRead, DashboardCreate>(
    {
      mutationFn: (guildId, data) => createDashboardApiV1GGuildIdDashboardsPost(guildId, data),
      invalidate: () => invalidateAllDashboards(),
      errorKey: "dashboards:error",
    },
    options
  );

export const useUpdateDashboard = (
  dashboardId: number,
  options?: MutationOpts<DashboardRead, DashboardUpdate>
) =>
  useGuildMutation<DashboardRead, DashboardUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateDashboardApiV1GGuildIdDashboardsDashboardIdPatch(guildId, dashboardId, data),
      invalidate: () => invalidateDashboardAndList(dashboardId),
      errorKey: "dashboards:error",
    },
    options
  );

export const useDeleteDashboard = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, dashboardId) =>
        deleteDashboardApiV1GGuildIdDashboardsDashboardIdDelete(guildId, dashboardId),
      invalidate: () => invalidateAllDashboards(),
      errorKey: "dashboards:error",
    },
    options
  );

// ── Grants Mutation (unified resource sharing) ──────────────────────────────

export const useSetDashboardGrants = (
  dashboardId: number,
  options?: MutationOpts<DashboardRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<DashboardRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setDashboardGrantsApiV1GGuildIdDashboardsDashboardIdGrantsPut(guildId, dashboardId, grants),
      invalidate: () => invalidateDashboardAndList(dashboardId),
      errorKey: "dashboards:error",
    },
    options
  );
