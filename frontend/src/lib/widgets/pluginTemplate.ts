/**
 * A plug-in widget's template, compiled against what it may read.
 *
 * A plug-in widget is one of its read endpoints drawn by a template, so the
 * template reads that endpoint's answer: `rows`, one entry per index across its
 * `list` returns, and `values`, its single returns. Each field is checked
 * against the returns the endpoint declares, `strings.<key>` against the
 * widget's own words, and the template is held to the plug-in limits.
 *
 * The one compile both sides run: the server when a plug-in is published, to
 * refuse a template that does not compile, and the browser before it draws one.
 *
 * Kept free of the browser and of `@/` imports: the server runs it.
 */

import { type CompileResult, compileTemplate } from "../templates/compile.ts";
import type { Shape } from "../templates/shapes.ts";
import { WIDGET_ELEMENTS } from "./elements.ts";

/** One of an endpoint's declared returns, as the contract writes it. */
export interface EndpointReturn {
  key: string;
  type: string;
  list?: boolean;
}

/** A plug-in widget as a tile draws it: its template, the returns of the
 *  endpoint it draws, and its own words, each by language. */
export interface PluginWidgetDrawing {
  template: string;
  returns: readonly EndpointReturn[];
  strings: Readonly<Record<string, Readonly<Record<string, string>>>>;
}

/** What each return type holds, as a template reads it. */
const RETURN_SHAPES: Readonly<Record<string, Shape>> = {
  bool: "boolean",
  datetime: "string",
  int: "number",
  string: "string",
  url: "string",
};

/** What a plug-in widget's template may read. */
export function pluginWidgetScope(
  returns: readonly EndpointReturn[],
  stringKeys: readonly string[]
): Record<string, Shape> {
  const row: Record<string, Shape> = {};
  const values: Record<string, Shape> = {};
  for (const declared of returns) {
    (declared.list ? row : values)[declared.key] = RETURN_SHAPES[declared.type] ?? "any";
  }
  return {
    rows: { list: { fields: row } },
    values: { fields: values },
    strings: { fields: Object.fromEntries(stringKeys.map((key) => [key, "string"])) },
    now: "number",
  };
}

export const compilePluginWidget = (
  source: string,
  returns: readonly EndpointReturn[],
  stringKeys: readonly string[]
): CompileResult =>
  compileTemplate(source, {
    name: "plug-in widget",
    section: { data: {}, parts: {} },
    scope: pluginWidgetScope(returns, stringKeys),
    elements: WIDGET_ELEMENTS,
    plugin: true,
  });
