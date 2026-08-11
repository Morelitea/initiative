/**
 * The built-in widget registry.
 *
 * Each entry is a widget module's *source*, imported with Vite's `?raw` so it
 * reaches the sandbox exactly as a marketplace listing's would — as text to be
 * evaluated, never as app code linked into the bundle. That is what keeps the
 * built-ins honest: they cannot accidentally acquire a capability a listing's
 * widget would not have, because they are shipped and executed the same way.
 *
 * The keys mirror `WIDGET_SPECS` in the backend's
 * `app/services/tenant/dashboard_definition.py`, which is the authority on
 * which types exist and what each may bind to. `registry.test.ts` compares the
 * two and fails on drift.
 */

import chartSource from "./builtins/chart.widget.js?raw";
import funnelSource from "./builtins/funnel.widget.js?raw";
import ganttSource from "./builtins/gantt.widget.js?raw";
import heatmapSource from "./builtins/heatmap.widget.js?raw";
import progressSource from "./builtins/progress.widget.js?raw";
import statSource from "./builtins/stat.widget.js?raw";
import tableSource from "./builtins/table.widget.js?raw";

/**
 * Module source per built-in type — and *only* that. Which sources a widget may
 * bind to, its size floors, and its display options all live in the backend's
 * `WIDGET_SPECS` and arrive over `GET …/dashboards/widget-catalog`, so there is
 * no second copy of the vocabulary to drift.
 */
export const BUILTIN_WIDGETS: Record<string, string> = {
  gantt: ganttSource,
  stat: statSource,
  chart: chartSource,
  funnel: funnelSource,
  progress: progressSource,
  heatmap: heatmapSource,
  table: tableSource,
};

export const BUILTIN_WIDGET_TYPES = Object.keys(BUILTIN_WIDGETS);

/** A widget module by type, or `undefined` for a type this build has no
 *  renderer for — which is how an installed listing naming a newer primitive
 *  surfaces as a clear tile rather than a crash. */
export const builtinWidgetSource = (type: string): string | undefined =>
  Object.hasOwn(BUILTIN_WIDGETS, type) ? BUILTIN_WIDGETS[type] : undefined;
