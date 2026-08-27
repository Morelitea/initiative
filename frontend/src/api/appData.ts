/**
 * The widget data plane: what an installed app contributes, and its rows.
 *
 * Hand-written rather than generated for the same reason `appConnections.ts` is
 * — these routes carry a rule worth keeping visible at the call site. **A widget
 * never names an address.** It names a read endpoint on an installed app, and
 * the request below carries the dashboard that widget sits on, because the
 * dashboard's own gates are what decide whether this viewer may see anything
 * here at all. There is no variant of this call that omits it.
 *
 * The *shapes* are the generated ones, re-exported rather than restated. They
 * were hand-copied here while the endpoints were being built, and a second
 * declaration of one contract is a second thing to remember: the copy went
 * stale through a vocabulary change without anything failing, because nothing
 * outside this file read the generated originals.
 */

import { apiClient } from "@/api/client";
import type {
  AppDataParam,
  AppDataResponse,
  AppEndpointRead,
  AppWidgetCatalogEntry,
  AppWidgetCatalogResponse,
  AppWidgetRead,
} from "@/api/generated/initiativeAPI.schemas";

export type {
  AppDataParam,
  AppDataResponse,
  AppEndpointRead,
  AppWidgetCatalogEntry,
  AppWidgetCatalogResponse,
  AppWidgetRead,
};

/** A localized label, as the app's manifest supplies it. */
export type LocalizedText = Record<string, string>;

export const getAppWidgetCatalog = (guildId: number) =>
  apiClient.get<AppWidgetCatalogResponse>(`/g/${guildId}/apps/widget-catalog`).then((r) => r.data);

export interface AppDataRequest {
  guildId: number;
  appId: number;
  endpointId: string;
  /** The dashboard the widget sits on. Required: it is the surface whose gates
   *  decide this read. */
  dashboardId: number;
  params?: Record<string, unknown>;
}

export const getAppData = ({ guildId, appId, endpointId, dashboardId, params }: AppDataRequest) =>
  apiClient
    .get<AppDataResponse>(
      `/g/${guildId}/apps/${appId}/endpoints/${encodeURIComponent(endpointId)}`,
      {
        params: {
          dashboard_id: dashboardId,
          // Sent as one encoded object so the server validates it against the
          // endpoint's own `params` rather than reading loose query keys.
          ...(params && Object.keys(params).length ? { params: JSON.stringify(params) } : {}),
        },
      }
    )
    .then((r) => r.data);

/** Find the install backing a binding's `app_uid`, and the widget/endpoint it
 *  names. Returns `undefined` for an app that is not installed here, which is
 *  what an imported definition referencing an app this guild does not have
 *  looks like. */
export const resolveAppBinding = (
  catalog: AppWidgetCatalogResponse | undefined,
  appUid: string | null | undefined,
  endpointId: string | null | undefined
): { entry: AppWidgetCatalogEntry; source: AppEndpointRead } | undefined => {
  if (!appUid || !endpointId) return undefined;
  const entry = (catalog?.items ?? []).find((item) => item.app_uid === appUid);
  const source = (entry?.endpoints ?? []).find((candidate) => candidate.id === endpointId);
  return entry && source ? { entry, source } : undefined;
};

/** The module a namespaced widget type resolves to, from the pinned definition
 *  the install carries. `undefined` means this build has nothing to run — the
 *  app was uninstalled, or its version stopped shipping that widget. */
export const appWidgetSource = (
  catalog: AppWidgetCatalogResponse | undefined,
  widgetType: string
): string | undefined => {
  for (const entry of catalog?.items ?? []) {
    const widget = (entry.widgets ?? []).find((candidate) => candidate.type === widgetType);
    if (widget) return widget.module_source;
  }
  return undefined;
};

/** Sample rows an app shipped for one of its widgets, in the shape a preview
 *  hands to the sandbox. Previews never call the network, so this is the only
 *  thing a marketplace listing's widget is ever drawn with. */
export const appWidgetSample = (
  catalog: AppWidgetCatalogResponse | undefined,
  widgetType: string,
  endpointId: string | null | undefined
): unknown[] => {
  for (const entry of catalog?.items ?? []) {
    const widget = (entry.widgets ?? []).find((candidate) => candidate.type === widgetType);
    if (!widget) continue;
    const rows = endpointId ? widget.sample_data?.[endpointId] : undefined;
    return Array.isArray(rows) ? rows : [];
  }
  return [];
};
