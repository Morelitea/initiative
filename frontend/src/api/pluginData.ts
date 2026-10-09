/**
 * The widget data plane: what an installed plug-in contributes, and its rows.
 *
 * Hand-written rather than generated because these routes carry a rule worth
 * keeping visible at the call site. **A widget
 * never names an address.** It names a read endpoint on an installed plug-in, and
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
  PluginDataParam,
  PluginDataResponse,
  PluginEndpointRead,
  PluginParamOption,
  PluginParamOptionSource,
  PluginParamOptionsResponse,
  PluginWidgetCatalogEntry,
  PluginWidgetCatalogResponse,
  PluginWidgetRead,
} from "@/api/generated/initiativeAPI.schemas";
import { isPluginWidgetType } from "@/lib/widgets/definition";
import type { PluginWidgetDrawing } from "@/lib/widgets/pluginTemplate";

export type {
  PluginDataParam,
  PluginDataResponse,
  PluginEndpointRead,
  PluginParamOption,
  PluginParamOptionSource,
  PluginParamOptionsResponse,
  PluginWidgetCatalogEntry,
  PluginWidgetCatalogResponse,
  PluginWidgetRead,
};

export const getPluginWidgetCatalog = (communityId: number) =>
  apiClient
    .get<PluginWidgetCatalogResponse>(`/c/${communityId}/plugins/widget-catalog`)
    .then((r) => r.data);

export interface PluginDataRequest {
  communityId: number;
  pluginId: number;
  endpointId: string;
  /** The dashboard the widget sits on. Required: it is the surface whose gates
   *  decide this read. */
  dashboardId: number;
  params?: Record<string, unknown>;
  /** Which widget on that dashboard is asking. The server runs the statement
   *  stored on it, if it has one; nothing here says what to run. */
  widgetId?: string;
}

export const getPluginData = ({
  communityId,
  pluginId,
  endpointId,
  dashboardId,
  params,
  widgetId,
}: PluginDataRequest) =>
  apiClient
    .get<PluginDataResponse>(
      `/c/${communityId}/plugins/${pluginId}/endpoints/${encodeURIComponent(endpointId)}`,
      {
        params: {
          dashboard_id: dashboardId,
          // Sent as one encoded object so the server validates it against the
          // endpoint's own `params` rather than reading loose query keys.
          ...(params && Object.keys(params).length ? { params: JSON.stringify(params) } : {}),
          ...(widgetId ? { widget_id: widgetId } : {}),
        },
      }
    )
    .then((r) => r.data);

export interface PluginParamOptionsRequest {
  communityId: number;
  pluginId: number;
  endpointId: string;
  /** Which of the endpoint's parameters to fill a menu for. */
  param: string;
  /** What the form has answered so far. Only the answers the source's own
   *  `needs` names are forwarded — the rest never leaves this process. */
  params?: Record<string, unknown>;
}

/**
 * The values one parameter permits, from the read its plug-in named for it.
 *
 * The one call here that carries no dashboard, and it cannot: a form is filled
 * in before a widget is placed, so there is no dashboard whose gates could
 * decide it. What decides it instead is that the caller does not name what gets
 * called — the source is read out of the plug-in's own declaration, and it is
 * fetched on the caller's own credentials.
 */
export const getPluginParamOptions = ({
  communityId,
  pluginId,
  endpointId,
  param,
  params,
}: PluginParamOptionsRequest) =>
  apiClient
    .get<PluginParamOptionsResponse>(
      `/c/${communityId}/plugins/${pluginId}/endpoints/${encodeURIComponent(endpointId)}/options`,
      {
        params: {
          param,
          ...(params && Object.keys(params).length ? { params: JSON.stringify(params) } : {}),
        },
      }
    )
    .then((r) => r.data);

/**
 * The install a plug-in binding reads, which of its reads, and the parameters
 * to send. `undefined` for a plug-in that is not installed here, which is what an
 * imported definition referencing a plug-in this community does not have looks
 * like, or a read its pinned version does not offer.
 *
 * A plug-in's own widget reads the endpoint it declares, whatever its stored
 * binding names, and sends only the parameters that endpoint declares: a tile
 * placed under an earlier release reads what the widget reads now. One of ours
 * reads the endpoint its binding names.
 */
export const resolvePluginBinding = (
  catalog: PluginWidgetCatalogResponse | undefined,
  binding: {
    plugin_uid?: string | null;
    endpoint_id?: string | null;
    params?: Record<string, unknown> | null;
  },
  widgetType: string | undefined
):
  | {
      entry: PluginWidgetCatalogEntry;
      source: PluginEndpointRead;
      params: Record<string, unknown> | undefined;
    }
  | undefined => {
  const entry = (catalog?.items ?? []).find((item) => item.plugin_uid === binding.plugin_uid);
  if (!entry) return undefined;
  const endpointId =
    widgetType && isPluginWidgetType(widgetType)
      ? (entry.widgets ?? []).find((widget) => widget.type === widgetType)?.endpoint
      : binding.endpoint_id;
  const source = (entry.endpoints ?? []).find((candidate) => candidate.id === endpointId);
  if (!source) return undefined;
  const declared = new Set((source.params ?? []).map((param) => param.key));
  const kept = Object.entries(binding.params ?? {}).filter(([key]) => declared.has(key));
  return { entry, source, params: kept.length ? Object.fromEntries(kept) : undefined };
};

/** The install a namespaced widget type belongs to, and that widget's own entry.
 *  `undefined` for a type this community has no install for — an imported
 *  definition naming a plug-in nobody here has. */
export const pluginWidgetEntry = (
  catalog: PluginWidgetCatalogResponse | undefined,
  widgetType: string
): { entry: PluginWidgetCatalogEntry; widget: PluginWidgetRead } | undefined => {
  for (const entry of catalog?.items ?? []) {
    const widget = (entry.widgets ?? []).find((candidate) => candidate.type === widgetType);
    if (widget) return { entry, widget };
  }
  return undefined;
};

/** A plug-in widget as a tile draws it: its template, the returns of the
 *  endpoint it draws, and its own words. `undefined` means this build has
 *  nothing to draw — the plug-in was uninstalled, or its version stopped
 *  shipping that widget. */
export const pluginWidgetDrawing = (
  catalog: PluginWidgetCatalogResponse | undefined,
  widgetType: string
): PluginWidgetDrawing | undefined => {
  const found = pluginWidgetEntry(catalog, widgetType);
  if (!found) return undefined;
  const { entry, widget } = found;
  return {
    template: widget.template,
    returns:
      (entry.endpoints ?? []).find((candidate) => candidate.id === widget.endpoint)?.returns ?? [],
    strings: widget.strings ?? {},
  };
};

/** One data source as a widget is handed it: the endpoint's `list` returns read
 *  side by side, and its single-valued ones once. */
export interface PluginSample {
  rows: Record<string, unknown>[];
  values: Record<string, unknown>;
}

const EMPTY_SAMPLE: PluginSample = { rows: [], values: {} };

/** `sample_data` reaches us as an opaque object — the catalog has projected it
 *  already, and this is where that becomes a type. */
const asSample = (raw: unknown): PluginSample => {
  if (!raw || typeof raw !== "object") return EMPTY_SAMPLE;
  const { rows, values } = raw as Partial<PluginSample>;
  return {
    rows: Array.isArray(rows) ? rows : [],
    values: values && typeof values === "object" ? values : {},
  };
};

/** The sample a plug-in shipped for one of its widgets, in the shape its
 *  template reads. The catalog has already read it through the endpoint's
 *  returns, exactly as it reads a live answer, so a preview draws the widget a
 *  community would get. Previews never call the network, so this is the only thing
 *  a marketplace listing's widget is ever drawn with. */
export const pluginWidgetSample = (
  catalog: PluginWidgetCatalogResponse | undefined,
  widgetType: string
): PluginSample => asSample(pluginWidgetEntry(catalog, widgetType)?.widget.sample_data);

/** One block's rows for a view's tasks, keyed by task id; a task with no row is absent. */
export interface PluginBlockRowsResponse {
  rows: Record<string, Record<string, unknown>>;
  fetched_at: string;
  cached: boolean;
}

export interface PluginBlockRequest {
  communityId: number;
  pluginId: number;
  blockId: string;
}

/**
 * A block's rows for these tasks, at most the contract's `blockSubjectIds` of
 * them. The block names its own endpoint; the server reads the tasks as the
 * viewer before the plug-in is asked about any of them.
 */
export const getPluginBlockRows = (
  { communityId, pluginId, blockId }: PluginBlockRequest,
  taskIds: readonly number[]
) =>
  apiClient
    .post<PluginBlockRowsResponse>(
      `/c/${communityId}/plugins/${pluginId}/blocks/${encodeURIComponent(blockId)}/rows`,
      { task_ids: taskIds }
    )
    .then((r) => r.data);

/** Run one of a block's actions for a task, by its key; the answer is the task's fresh row. */
export const runPluginBlockAction = (
  { communityId, pluginId, blockId }: PluginBlockRequest,
  actionKey: string,
  taskId: number
) =>
  apiClient
    .post<{ row: Record<string, unknown> | null }>(
      `/c/${communityId}/plugins/${pluginId}/blocks/${encodeURIComponent(blockId)}/actions/${encodeURIComponent(actionKey)}`,
      { task_id: taskId }
    )
    .then((r) => r.data);
