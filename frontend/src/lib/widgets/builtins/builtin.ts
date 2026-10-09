/**
 * What a built-in widget is: its own words, the code that works out what to
 * draw from its data, and the template that draws it.
 *
 * The code is ours, so it runs in the app like any component's. It returns a
 * model: which picture to draw and its props, or why there is nothing to draw.
 * The template (`<type>.widget.html`) places it, so the layout is a template's
 * as every community screen's is.
 */

import type { CompiledTemplate } from "@/lib/templates/compile";

import type { TabularData, WidgetConfig } from "../dataShapes";
import type { LocalizedText, WidgetMeta } from "../widgetMeta";

/** What the host knows that the data does not say. */
export interface WidgetContext {
  /** The viewer's language tag. */
  locale?: string;
  /** Which of the data's columns fill each of the widget's slots. */
  slots?: Record<string, number[]>;
  /** The minute the widget is drawn for, in epoch milliseconds. */
  now?: number;
}

export interface BuiltinWidget {
  /** Its name, description and option labels, per language, as a plug-in's are. */
  meta: WidgetMeta;
  shape: (data: TabularData, config: WidgetConfig, context: WidgetContext) => unknown;
  template: CompiledTemplate;
}

/** A widget's own words, keyed, per language. */
export type WidgetStrings = Record<string, LocalizedText>;

/** Its words in the viewer's language, then the base language, then English. */
export const sayer =
  (strings: WidgetStrings, locale = "en") =>
  (key: string): string => {
    const entry = strings[key] ?? {};
    return entry[locale] ?? entry[locale.split("-")[0] as string] ?? entry.en ?? key;
  };

/** Nothing to draw, and why. */
export const empty = (message: string) => ({ kind: "empty", message }) as const;
