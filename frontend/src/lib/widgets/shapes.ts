/**
 * What each built-in widget draws, mirrored from the backend's `WIDGET_SPECS`.
 *
 * The served widget catalog is the authority, and a placed tile reads it. This
 * copy exists for the two places that have no catalog to read: the marketplace
 * preview, which is looking at a listing it has not installed and so has no
 * guild to fetch one from, and the widget tests, which run without a backend.
 *
 * `dashboards_test.py` is what would catch the served shapes and the declared
 * ones drifting; this file drifting from either shows up as a preview that
 * draws nothing.
 */

import type { WidgetSlot } from "@/api/generated/initiativeAPI.schemas";

const slot = (
  name: string,
  types: string[],
  extra: { required?: boolean; repeatable?: boolean } = {}
): WidgetSlot => ({ name, types, required: true, repeatable: false, ...extra }) as WidgetSlot;

const LABEL = ["text", "enum", "reference"];

export const BUILTIN_SHAPES: Record<string, WidgetSlot[]> = {
  gantt: [
    slot("label", LABEL),
    slot("start", ["date"]),
    slot("end", ["date"]),
    slot("group", LABEL, { required: false }),
  ],
  stat: [slot("value", ["number"]), slot("label", LABEL, { required: false })],
  chart: [slot("label", [...LABEL, "date"]), slot("value", ["number"], { repeatable: true })],
  funnel: [slot("label", LABEL), slot("value", ["number"])],
  progress: [
    slot("value", ["number"]),
    slot("total", ["number"], { required: false }),
    slot("label", LABEL, { required: false }),
  ],
  heatmap: [slot("at", ["date"]), slot("value", ["number"])],
  board: [slot("card", LABEL), slot("column", LABEL), slot("date", ["date"], { required: false })],
  // Draws whatever it is given, which is what makes it the fallback.
  table: [],
};

/** The shape a widget declares — the served catalog's answer, or this build's
 *  own for a preview that has no catalog to ask. */
export const shapeFor = (
  type: string,
  served?: { widgets: { type: string; shape: WidgetSlot[] }[] }
): WidgetSlot[] =>
  served?.widgets.find((entry) => entry.type === type)?.shape ?? BUILTIN_SHAPES[type] ?? [];
