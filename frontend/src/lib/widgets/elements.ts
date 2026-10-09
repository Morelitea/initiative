/**
 * The widget elements: what a widget template may place to draw data.
 *
 * Each is one of our components, given its props by the template:
 *
 *   <chart :mark="model.mark" :series="model.series" />
 *
 * The compiler checks the prop names against this list. The values are checked
 * when the widget draws, because they are data the compiler never saw.
 *
 * Kept free of the browser and of `@/` imports: the Vite plugin reads it in
 * Node to compile the built-in widgets' templates.
 */

import type { Shape } from "../templates/shapes.ts";

/**
 * What a widget template reads: the model its code worked out from the data,
 * the widget's options, and the minute it is drawn for. The model is the
 * code's own, so its fields are not checked.
 */
export const WIDGET_SCOPE: Readonly<Record<string, Shape>> = {
  model: "any",
  config: { map: "string" },
  now: "number",
};

export interface WidgetElementDefinition {
  /** The kind of picture it draws, as the drawing components name it. */
  kind: "metric" | "series" | "timeline" | "funnel" | "progress" | "matrix" | "table" | "board";
  /** Its props, as the template writes them (`x-label`) mapped to the names the
   *  component takes (`xLabel`). */
  props: Readonly<Record<string, string>>;
}

/** `xLabel` as a template writes it: `x-label`. */
const attribute = (prop: string) => prop.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);

const define = (
  kind: WidgetElementDefinition["kind"],
  props: readonly string[]
): WidgetElementDefinition => ({
  kind,
  props: Object.fromEntries(props.map((prop) => [attribute(prop), prop])),
});

export const WIDGET_ELEMENTS: Readonly<Record<string, WidgetElementDefinition>> = {
  metric: define("metric", ["value", "label", "format", "delta", "deltaGood", "caption", "tone"]),
  chart: define("series", [
    "mark",
    "series",
    "stacked",
    "format",
    "xLabel",
    "yLabel",
    "xTime",
    "showLegend",
    "labels",
    "target",
    "targetLabel",
    "emphasis",
    "horizontal",
  ]),
  timeline: define("timeline", ["lanes", "start", "end", "scale", "now"]),
  funnel: define("funnel", ["stages", "format"]),
  progress: define("progress", [
    "value",
    "min",
    "max",
    "label",
    "caption",
    "tone",
    "format",
    "target",
  ]),
  heatmap: define("matrix", ["cells", "max", "xLabels", "yLabels", "tone"]),
  "data-table": define("table", ["columns", "rows"]),
  board: define("board", ["columns"]),
};
