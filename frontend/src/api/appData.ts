/**
 * The widget data plane: what an installed app contributes, and its rows.
 *
 * Hand-written rather than generated for the same reason `appConnections.ts` is
 * — these routes carry a rule worth keeping visible at the call site. **A widget
 * never names an endpoint.** It names a source on an installed app, and the
 * request below carries the dashboard that widget sits on, because the
 * dashboard's own gates are what decide whether this viewer may see anything
 * here at all. There is no variant of this call that omits it.
 *
 * The shapes mirror `backend/app/schemas/tenant/app_data.py`. Once Orval has run
 * against the new endpoints these can be swapped for the generated equivalents;
 * the field names are already the generated ones.
 */

import { apiClient } from "@/api/client";

/** A localized label, as the app's manifest supplies it. */
export type LocalizedText = Record<string, string>;

/** One parameter a source accepts. The manifest's closed enum, minus `secret` —
 *  a credential is supplied once and held in custody, never restated per call. */
export interface AppDataParam {
  key: string;
  type: "string" | "url" | "bool" | "select" | "int";
  label: LocalizedText;
  required?: boolean;
  options?: string[];
}

export interface AppDataSource {
  id: string;
  /** `member` or `guild_admin`. Shown by the picker; enforced again on every
   *  fetch under the caller's own session, so this is not what protects it. */
  visibility: "member" | "guild_admin" | string;
  /** What the app asks for. The proxy applies the deployment's own ceiling on
   *  top, so this is a request rather than a guarantee. */
  cache_ttl_seconds: number;
  params_schema: AppDataParam[];
}

export interface AppWidget {
  /** Namespaced `app:<listing_uid>:<widget_id>` — an app's widget can never
   *  resolve to a built-in renderer, or the other way round. */
  type: string;
  id: string;
  meta: Record<string, unknown>;
  /** The module the sandbox runs. Text everywhere outside that sandbox. */
  module_source: string;
  sources: string[];
  /** Rows for a preview that issues no request at all, keyed by source id. */
  sample_data: Record<string, unknown>;
}

export interface AppWidgetCatalogEntry {
  app_id: number;
  app_uid: string;
  name: string;
  enabled: boolean;
  widgets: AppWidget[];
  data_sources: AppDataSource[];
}

export interface AppWidgetCatalog {
  items: AppWidgetCatalogEntry[];
}

export interface AppDataResponse {
  /** Verbatim from the app. Nothing between there and the sandbox reads inside
   *  them, and the sandbox receives them as values, never as markup. */
  rows: unknown[];
  /** When the upstream call happened — a cached body keeps the time it was
   *  actually obtained, not the time it was asked for. */
  fetched_at: string;
  cached: boolean;
}

export const getAppWidgetCatalog = (guildId: number) =>
  apiClient.get<AppWidgetCatalog>(`/g/${guildId}/apps/widget-catalog`).then((r) => r.data);

export interface AppDataRequest {
  guildId: number;
  appId: number;
  sourceId: string;
  /** The dashboard the widget sits on. Required: it is the surface whose gates
   *  decide this read. */
  dashboardId: number;
  params?: Record<string, unknown>;
}

export const getAppData = ({ guildId, appId, sourceId, dashboardId, params }: AppDataRequest) =>
  apiClient
    .get<AppDataResponse>(`/g/${guildId}/apps/${appId}/data/${encodeURIComponent(sourceId)}`, {
      params: {
        dashboard_id: dashboardId,
        // Sent as one encoded object so the server validates it against the
        // source's own `params_schema` rather than reading loose query keys.
        ...(params && Object.keys(params).length ? { params: JSON.stringify(params) } : {}),
      },
    })
    .then((r) => r.data);

/** Find the install backing a binding's `app_uid`, and the widget/source it
 *  names. Returns `undefined` for an app that is not installed here, which is
 *  what an imported definition referencing an app this guild does not have
 *  looks like. */
export const resolveAppBinding = (
  catalog: AppWidgetCatalog | undefined,
  appUid: string | null | undefined,
  sourceId: string | null | undefined
): { entry: AppWidgetCatalogEntry; source: AppDataSource } | undefined => {
  if (!appUid || !sourceId) return undefined;
  const entry = catalog?.items.find((item) => item.app_uid === appUid);
  const source = entry?.data_sources.find((candidate) => candidate.id === sourceId);
  return entry && source ? { entry, source } : undefined;
};

/** The module a namespaced widget type resolves to, from the pinned definition
 *  the install carries. `undefined` means this build has nothing to run — the
 *  app was uninstalled, or its version stopped shipping that widget. */
export const appWidgetSource = (
  catalog: AppWidgetCatalog | undefined,
  widgetType: string
): string | undefined => {
  for (const entry of catalog?.items ?? []) {
    const widget = entry.widgets.find((candidate) => candidate.type === widgetType);
    if (widget) return widget.module_source;
  }
  return undefined;
};

/** Sample rows an app shipped for one of its widgets, in the shape a preview
 *  hands to the sandbox. Previews never call the network, so this is the only
 *  thing a marketplace listing's widget is ever drawn with. */
export const appWidgetSample = (
  catalog: AppWidgetCatalog | undefined,
  widgetType: string,
  sourceId: string | null | undefined
): unknown[] => {
  for (const entry of catalog?.items ?? []) {
    const widget = entry.widgets.find((candidate) => candidate.type === widgetType);
    if (!widget) continue;
    const rows = sourceId ? widget.sample_data?.[sourceId] : undefined;
    return Array.isArray(rows) ? rows : [];
  }
  return [];
};
