/**
 * Reading and editing a dashboard definition, client-side.
 *
 * The backend's `dashboard_definition.py` is the authority: it normalizes and
 * validates every write, and its `WIDGET_SPECS` decides which widget types and
 * binding sources exist. Nothing here re-implements that. What this does is the
 * part only the client needs — describe the stored JSON in TypeScript, and edit
 * it as immutable values so the canvas can compute a change, save it, and let
 * the server's normalization come back as the truth.
 */

import type { WidgetCatalog, WidgetCatalogEntry } from "@/api/generated/initiativeAPI.schemas";
import type { WidgetBinding } from "@/hooks/useWidgetData";

export const DEFINITION_SCHEMA_VERSION = 1;
/** Mirrors MAX_WIDGETS in the backend validator; the canvas stops offering
 *  "add widget" here rather than letting a save 422. */
export const MAX_WIDGETS = 50;
export const GRID_COLUMNS = 12;

export interface WidgetGrid {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DefinitionWidget {
  id: string;
  type: string;
  grid: WidgetGrid;
  binding: WidgetBinding;
  title?: string;
  preset?: string;
  options?: Record<string, string>;
}

export interface DashboardDefinition {
  schema_version: number;
  kind: "dashboard";
  layout: { columns: number };
  widgets: DefinitionWidget[];
}

export interface DashboardConfig {
  widgets: Record<string, Record<string, unknown>>;
}

export const EMPTY_DEFINITION: DashboardDefinition = {
  schema_version: DEFINITION_SCHEMA_VERSION,
  kind: "dashboard",
  layout: { columns: GRID_COLUMNS },
  widgets: [],
};

/** Read a stored definition, tolerating the empty object a dashboard is created
 *  with and anything older than the current shape. */
export const readDefinition = (raw: unknown): DashboardDefinition => {
  if (typeof raw !== "object" || raw === null) return EMPTY_DEFINITION;
  const value = raw as Partial<DashboardDefinition>;
  return {
    schema_version: DEFINITION_SCHEMA_VERSION,
    kind: "dashboard",
    layout: { columns: value.layout?.columns ?? GRID_COLUMNS },
    widgets: Array.isArray(value.widgets) ? value.widgets : [],
  };
};

export const readConfig = (raw: unknown): DashboardConfig => {
  if (typeof raw !== "object" || raw === null) return { widgets: {} };
  const value = raw as Partial<DashboardConfig>;
  return { widgets: value.widgets ?? {} };
};

/**
 * A widget's effective binding: the definition's, with the instance config's
 * values layered on top.
 *
 * This is the seam that makes an installed listing work. A catalog definition
 * leaves the ids it cannot know as null — no listing knows this guild's counter
 * ids — and the config fills them in per install.
 */
export const effectiveBinding = (
  widget: DefinitionWidget,
  config: DashboardConfig
): WidgetBinding => ({
  ...widget.binding,
  ...(config.widgets[widget.id] ?? {}),
});

/**
 * The prefix an installed app's widget types carry.
 *
 * Mirrors `APP_WIDGET_TYPE_PREFIX` in the backend's `service_apps.py`. A type is
 * `app:<listing_uid>:<widget_id>`, and `:` is outside the identifier character
 * set both halves use, so the three parts stay unambiguous. The namespacing is
 * what stops an app's widget resolving to a built-in renderer, or a built-in
 * resolving to an app's module.
 */
export const APP_WIDGET_TYPE_PREFIX = "app:";

export const isAppWidgetType = (type: string): boolean => type.startsWith(APP_WIDGET_TYPE_PREFIX);

/** The listing uid and widget id inside a namespaced type, or `undefined` for
 *  anything that is not one. */
export const appWidgetParts = (
  type: string
): { listingUid: string; widgetId: string } | undefined => {
  if (!isAppWidgetType(type)) return undefined;
  const [listingUid, widgetId] = type.slice(APP_WIDGET_TYPE_PREFIX.length).split(":");
  return listingUid && widgetId ? { listingUid, widgetId } : undefined;
};

/** Slots a widget still needs filled before it can draw anything.
 *
 *  Re-exported from the source registry, which derives it from each
 *  parameter's own `required` flag — this used to be a second `switch` over the
 *  same knowledge. */
export { unboundSlots } from "@/lib/widgets/sources";

// --- editing ----------------------------------------------------------------

const nextWidgetId = (widgets: DefinitionWidget[]): string => {
  const taken = new Set(widgets.map((widget) => widget.id));
  for (let index = 1; ; index++) {
    const candidate = `w${index}`;
    if (!taken.has(candidate)) return candidate;
  }
};

/** The row below everything placed so far — where a new widget lands, rather
 *  than on top of an existing one. */
const bottomRow = (widgets: DefinitionWidget[]): number =>
  widgets.reduce((lowest, widget) => Math.max(lowest, widget.grid.y + widget.grid.h), 0);

export const catalogEntry = (
  catalog: WidgetCatalog | undefined,
  type: string
): WidgetCatalogEntry | undefined => catalog?.widgets.find((entry) => entry.type === type);

/**
 * Add a widget at its catalog default size.
 *
 * `options` are the display choices the picker made — the widget's own, checked
 * against the primitive's allow-list on save. A preset resolves to its primitive
 * with its fixed options applied *last*, because those are what make it that
 * preset; that is the same order the backend normalizer uses, so the canvas
 * draws what the round trip will return.
 */
export const addWidget = (
  definition: DashboardDefinition,
  catalog: WidgetCatalog | undefined,
  typeOrPreset: string,
  source: string,
  options?: Record<string, string>
): DashboardDefinition => {
  const preset = catalog?.presets.find((entry) => entry.name === typeOrPreset);
  const type = preset?.primitive ?? typeOrPreset;
  const entry = catalogEntry(catalog, type);
  const merged = { ...options, ...preset?.options };

  const widget: DefinitionWidget = {
    id: nextWidgetId(definition.widgets),
    type,
    grid: {
      x: 0,
      y: bottomRow(definition.widgets),
      w: entry?.default_w ?? 6,
      h: entry?.default_h ?? 4,
    },
    binding: { source } as WidgetBinding,
    ...(preset ? { preset: preset.name } : {}),
    ...(Object.keys(merged).length ? { options: merged } : {}),
  };

  return { ...definition, widgets: [...definition.widgets, widget] };
};

export const removeWidget = (
  definition: DashboardDefinition,
  widgetId: string
): DashboardDefinition => ({
  ...definition,
  widgets: definition.widgets.filter((widget) => widget.id !== widgetId),
});

export const updateWidget = (
  definition: DashboardDefinition,
  widgetId: string,
  patch: Partial<DefinitionWidget>
): DashboardDefinition => ({
  ...definition,
  widgets: definition.widgets.map((widget) =>
    widget.id === widgetId ? { ...widget, ...patch } : widget
  ),
});

/**
 * Apply a grid layout from the canvas, clamped to each widget's catalog floor.
 *
 * The clamp matters even though the backend re-clamps on save: it is what stops
 * a drag from momentarily rendering a Gantt two columns wide, and it keeps the
 * value we send equal to the value we drew.
 */
export const applyLayout = (
  definition: DashboardDefinition,
  catalog: WidgetCatalog | undefined,
  layout: { i: string; x: number; y: number; w: number; h: number }[]
): DashboardDefinition => {
  const byId = new Map(layout.map((item) => [item.i, item]));
  return {
    ...definition,
    widgets: definition.widgets.map((widget) => {
      const placed = byId.get(widget.id);
      if (!placed) return widget;
      const entry = catalogEntry(catalog, widget.type);
      return {
        ...widget,
        grid: {
          x: Math.max(0, placed.x),
          y: Math.max(0, placed.y),
          w: Math.min(GRID_COLUMNS, Math.max(placed.w, entry?.min_w ?? 1)),
          h: Math.max(placed.h, entry?.min_h ?? 1),
        },
      };
    }),
  };
};

/**
 * JSON with object keys in a fixed order, for comparing two definitions.
 *
 * `JSON.stringify` preserves insertion order, and the server's normalizer builds
 * its widgets in its own — so a widget that gained a title client-side
 * stringifies differently from the identical widget that came back from a save.
 * Comparing canonically is what lets the editor recognize its own work in the
 * server's copy and stop drawing the local one.
 */
export const canonicalJson = (value: unknown): string =>
  JSON.stringify(value, (_key, raw) => {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return raw;
    const record = raw as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(record)
        .sort((a, b) => (a < b ? -1 : 1))
        .map((key) => [key, record[key]])
    );
  });

/** Whether two definitions differ in a way worth saving. Layout callbacks fire
 *  on every drag frame; only a settled change should reach the API. */
export const definitionsEqual = (a: DashboardDefinition, b: DashboardDefinition): boolean =>
  canonicalJson(a) === canonicalJson(b);

/** Config entries for widgets the definition no longer has, dropped — mirrors
 *  what the backend does on save so the editor shows the same thing. */
export const pruneConfig = (
  definition: DashboardDefinition,
  config: DashboardConfig
): DashboardConfig => {
  const known = new Set(definition.widgets.map((widget) => widget.id));
  return {
    widgets: Object.fromEntries(
      Object.entries(config.widgets).filter(([widgetId]) => known.has(widgetId))
    ),
  };
};
