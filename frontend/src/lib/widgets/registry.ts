/**
 * The built-in widget registry.
 *
 * Each built-in is our own code and template (`builtins/<type>.widget.ts` and
 * `.widget.html`): the code works out what to draw from the binding's data, and
 * the template draws it with the widget elements.
 *
 * The keys mirror `WIDGET_SPECS` in the backend's
 * `app/services/tenant/dashboard_definition.py`, which is the authority on
 * which types exist and what each may bind to. `registry.test.ts` compares the
 * two and fails on drift.
 */

import { board } from "./builtins/board.widget";
import type { BuiltinWidget } from "./builtins/builtin";
import { chart } from "./builtins/chart.widget";
import { funnel } from "./builtins/funnel.widget";
import { gantt } from "./builtins/gantt.widget";
import { heatmap } from "./builtins/heatmap.widget";
import { progress } from "./builtins/progress.widget";
import { stat } from "./builtins/stat.widget";
import { table } from "./builtins/table.widget";

/**
 * Each built-in by type — and *only* that. Which sources a widget may bind to,
 * its size floors, and its display options all live in the backend's
 * `WIDGET_SPECS` and arrive over `GET …/dashboards/widget-catalog`, so there is
 * no second copy of the vocabulary to drift.
 */
const BUILTINS: Record<string, BuiltinWidget> = {
  gantt,
  stat,
  chart,
  funnel,
  progress,
  heatmap,
  table,
  board,
};

export const BUILTIN_WIDGET_TYPES = Object.keys(BUILTINS);

/** A built-in by type, or `undefined` for a type this build does not have —
 *  which is how an installed listing naming a newer primitive surfaces as a
 *  clear tile rather than a crash. */
export const builtinWidget = (type: string): BuiltinWidget | undefined =>
  Object.hasOwn(BUILTINS, type) ? BUILTINS[type] : undefined;
