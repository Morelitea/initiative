/**
 * The widget elements: what a widget template may place to draw data.
 *
 * Each is one of our components, given its props by the template:
 *
 *   <chart :mark="model.mark" :series="model.series" />
 *
 * Their names and props are the plug-in contract's (`templates.widgetElements`).
 * The compiler checks the prop names against them. The values are checked when
 * the widget draws, because they are data the compiler never saw.
 *
 * Kept free of the browser and of `@/` imports: the Vite plugin reads it in
 * Node to compile the built-in widgets' templates.
 */

import type { Shape } from "../templates/shapes.ts";
import { WIDGET_ELEMENT_PROPS } from "../templates/vocabulary.ts";

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

/** What each element the contract names is drawn as, by the drawing components. */
const KINDS: Readonly<Record<string, WidgetElementDefinition["kind"]>> = {
  metric: "metric",
  chart: "series",
  timeline: "timeline",
  funnel: "funnel",
  progress: "progress",
  heatmap: "matrix",
  "data-table": "table",
  board: "board",
};

/** `x-label` as the component takes it: `xLabel`. */
const camel = (attribute: string) =>
  attribute.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase());

/** The contract's widget elements, each with the component that draws it. */
export const WIDGET_ELEMENTS: Readonly<Record<string, WidgetElementDefinition>> =
  Object.fromEntries(
    Object.entries(WIDGET_ELEMENT_PROPS).flatMap(([name, props]) => {
      const kind = KINDS[name];
      return kind
        ? [[name, { kind, props: Object.fromEntries(props.map((prop) => [prop, camel(prop)])) }]]
        : [];
    })
  );
