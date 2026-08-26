/**
 * Reading an installed app's widgets, and the rows behind one.
 *
 * Two queries with deliberately different shapes.
 *
 * The **catalog** is per guild and shared by every widget on the canvas: one
 * request tells the page which apps contribute widgets, which module draws each
 * one, and what each source declares. It changes only when an app is installed,
 * upgraded, or turned off, so it is cached generously.
 *
 * The **data** query is per widget, per viewer, and carries the dashboard the
 * widget sits on — the surface whose gates decide the read. Its `staleTime`
 * comes from the app's own `cache_ttl_seconds`, capped here as well as on the
 * server: an app asking for a day of freshness would otherwise decide how stale
 * a dashboard may look, and the number crossing the wire is a request rather
 * than a promise.
 *
 * Two widgets bound to the same source with the same parameters share a key, so
 * a canvas showing one app's data twice issues one request — the same collapse
 * the server does across viewers, done here across tiles.
 */

import { useQuery } from "@tanstack/react-query";

import {
  type AppDataResponse,
  type AppWidgetCatalog,
  getAppData,
  getAppWidgetCatalog,
} from "@/api/appData";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

/** The client's own ceiling on how long an app's rows are reused, in seconds.
 *  Mirrors the proxy's `MAX_CACHE_TTL_SECONDS`; both exist because a listing
 *  must not be the thing that decides. */
export const MAX_APP_STALE_SECONDS = 300;

export const appWidgetCatalogKey = (guildId: number) => ["app-widget-catalog", guildId] as const;

export const appDataKey = (
  guildId: number,
  appId: number,
  endpointId: string,
  dashboardId: number,
  params: Record<string, unknown> | undefined
) =>
  [
    "app-data",
    guildId,
    appId,
    endpointId,
    dashboardId,
    // Canonical, so two widgets that bound the same parameters in a different
    // order still share one request. Parameter values are scalars, so a sorted
    // entry list is the whole of it.
    JSON.stringify(Object.entries(params ?? {}).sort(([a], [b]) => (a < b ? -1 : 1))),
  ] as const;

/** Which widgets this guild's installed apps contribute. Enabled installs only —
 *  a disabled app's widgets have nothing to draw. */
export const useAppWidgetCatalog = (enabled = true) => {
  const guildId = useActiveGuildId();
  return useQuery<AppWidgetCatalog>({
    queryKey: appWidgetCatalogKey(guildId),
    queryFn: () => getAppWidgetCatalog(guildId),
    enabled: enabled && Number.isFinite(guildId) && guildId > 0,
    // Installing or upgrading an app invalidates this explicitly; between those
    // it is effectively static for the page's lifetime.
    staleTime: 5 * 60_000,
  });
};

export interface AppDataQuery {
  appId: number | undefined;
  endpointId: string | undefined;
  dashboardId: number | undefined;
  params?: Record<string, unknown>;
  /** The source's declared freshness, in seconds. Capped before use. */
  cacheTtlSeconds?: number;
  enabled?: boolean;
}

/** One app data source, for this viewer, on this dashboard. */
export const useAppData = ({
  appId,
  endpointId,
  dashboardId,
  params,
  cacheTtlSeconds,
  enabled = true,
}: AppDataQuery) => {
  const guildId = useActiveGuildId();
  // Fail closed: without a guild, an install, a source *and* the dashboard the
  // widget sits on, there is nothing to ask for. A preview has none of them,
  // which is how it issues no request at all.
  const ready =
    enabled &&
    Number.isFinite(guildId) &&
    guildId > 0 &&
    typeof appId === "number" &&
    typeof dashboardId === "number" &&
    typeof endpointId === "string" &&
    endpointId.length > 0;

  const staleSeconds = Math.max(0, Math.min(cacheTtlSeconds ?? 0, MAX_APP_STALE_SECONDS));

  return useQuery<AppDataResponse>({
    queryKey: appDataKey(guildId, appId ?? 0, endpointId ?? "", dashboardId ?? 0, params),
    queryFn: () =>
      getAppData({
        guildId,
        appId: appId as number,
        endpointId: endpointId as string,
        dashboardId: dashboardId as number,
        params,
      }),
    enabled: ready,
    staleTime: staleSeconds * 1000,
    // An app that is down should not be hammered from every open tile, and the
    // tile has something useful to draw meanwhile: React Query keeps serving the
    // last good rows for the stale window while the error is shown.
    retry: false,
  });
};
