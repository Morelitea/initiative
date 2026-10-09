/**
 * One widget on a canvas: chrome, drawing the widget, and the failure path.
 *
 * The frame — border, title, loading state, error tile — is app code. A widget
 * contributes only what goes inside, drawn by a template: a built-in's code
 * works out what its template reads, and a plug-in's template reads its
 * endpoint's answer. No widget code runs from anyone else. That split is why a
 * broken or hostile widget costs one tile: it cannot draw its own frame, so it
 * cannot pretend to be the app around it.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { CompileResult } from "@/lib/templates/compile";
import { renderTemplate } from "@/lib/templates/render";
import { PLUGIN_CLASSES } from "@/lib/templates/vocabulary";
import { cn } from "@/lib/utils";
import type { BuiltinWidget } from "@/lib/widgets/builtins/builtin";
import type { PluginRows, TabularData, WidgetConfig, WidgetData } from "@/lib/widgets/dataShapes";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import { compilePluginWidget, type PluginWidgetDrawing } from "@/lib/widgets/pluginTemplate";
import { builtinWidget } from "@/lib/widgets/registry";
import { localized } from "@/lib/widgets/widgetMeta";

import { WIDGET_ELEMENT_COMPONENTS } from "./scene/widgetElements";
import { WidgetError } from "./WidgetError";

export interface WidgetTileProps {
  /** Widget type from the definition: a built-in's key, or a plug-in's namespaced type. */
  type: string;
  title?: string;
  data: WidgetData;
  config?: WidgetConfig;
  className?: string;
  /** A plug-in's widget, from the install's pinned definition, in place of a built-in. */
  plugin?: PluginWidgetDrawing;
  /** Which of the data's columns fill each of the widget's slots. Resolved by
   *  the caller, which is the only place that has the widget's declared shape
   *  and the author's overrides together. */
  slots?: Record<string, number[]>;
  /** Draw this failure instead of drawing the widget — for the one case the
   *  widget cannot speak to, its data never arriving. Running it over empty rows
   *  would show "nothing to display", which is a different and misleading claim
   *  from "the plug-in behind this is not answering". */
  errorCode?: WidgetErrorCode;
  /** The binding's own fetch is still in flight. Shown as a skeleton, so a
   *  widget does not flash empty then populate. */
  isLoading?: boolean;
  /** Drop the border and title — the canvas frames its own widgets, and two
   *  nested frames read as a bug. The widget still cannot escape its box. */
  chromeless?: boolean;
  /** Freeze the widget's clock. Previews render frozen sample data and pass
   *  the samples' own anchor here, so a clock-reading widget draws the same
   *  picture every time; live tiles omit it and get the real minute. */
  now?: number;
  /** Draw the pictures, or the same numbers as tables. The widget draws
   *  identically either way — each element draws its own table form — so
   *  nothing about a widget changes when a reader switches, and a widget cannot
   *  tell which one it is being read in. */
  view?: "scene" | "table";
}

/** The minute a widget is drawn for: rounded, so a clock-reading widget draws
 *  the same picture all minute and its answers can be reused. */
const thisMinute = () => Math.floor(Date.now() / 60_000) * 60_000;

export function WidgetTile(props: WidgetTileProps) {
  if (props.plugin) return <PluginTile {...props} plugin={props.plugin} />;
  const builtin = builtinWidget(props.type);
  if (builtin) return <BuiltinTile {...props} widget={builtin} />;
  return (
    <TileFrame {...props}>
      <WidgetError code={props.errorCode ?? WidgetErrorCode.TYPE_UNSUPPORTED} />
    </TileFrame>
  );
}

/**
 * A built-in: its code works out a model from the data, and its template draws
 * it with the widget elements.
 */
function BuiltinTile({
  widget,
  data,
  config,
  slots,
  errorCode,
  isLoading,
  now,
  view = "scene",
  ...frame
}: WidgetTileProps & { widget: BuiltinWidget }) {
  const { i18n } = useTranslation();
  const communityId = useActiveCommunityId();

  // What the template reads, worked out once per change, and the same object in
  // between so the template reuses its answers.
  const drawn = useMemo(() => {
    if (errorCode || isLoading) return null;
    const minute = now ?? thisMinute();
    try {
      const model = widget.shape(data as TabularData, config ?? {}, {
        locale: i18n.language,
        slots,
        now: minute,
      });
      return { ok: true as const, scope: { model, config: config ?? {}, now: minute } };
    } catch (error) {
      return {
        ok: false as const,
        code: WidgetErrorCode.THREW,
        detail: error instanceof Error ? error.message : String(error),
      };
    }
  }, [widget, data, config, slots, now, errorCode, isLoading, i18n.language]);

  const body = isLoading ? (
    <Skeleton className="h-full w-full" />
  ) : errorCode ? (
    <WidgetError code={errorCode} />
  ) : drawn && !drawn.ok ? (
    <WidgetError code={drawn.code} detail={drawn.detail} />
  ) : drawn ? (
    renderTemplate(widget.template, {
      data: drawn.scope,
      context: undefined,
      parts: {},
      communityId,
      elements: WIDGET_ELEMENT_COMPONENTS[view],
    })
  ) : null;

  return <TileFrame {...frame}>{body}</TileFrame>;
}

/** Each plug-in template, compiled once against what it reads, however many tiles draw it. */
const compiledTemplates = new Map<string, CompileResult>();

const compiled = (plugin: PluginWidgetDrawing): CompileResult => {
  const keys = Object.keys(plugin.strings);
  const key = JSON.stringify([plugin.template, plugin.returns, keys]);
  let result = compiledTemplates.get(key);
  if (!result) {
    result = compilePluginWidget(plugin.template, plugin.returns, keys);
    compiledTemplates.set(key, result);
  }
  return result;
};

/**
 * A plug-in's widget: its template, checked when the plug-in was published and
 * compiled again here, draws its endpoint's answer with the widget elements and
 * the classes the contract allows a plug-in.
 */
function PluginTile({
  plugin,
  data,
  errorCode,
  isLoading,
  now,
  view = "scene",
  ...frame
}: WidgetTileProps & { plugin: PluginWidgetDrawing }) {
  const { i18n } = useTranslation();
  const communityId = useActiveCommunityId();
  const result = useMemo(() => compiled(plugin), [plugin]);

  // What the template reads, the same object while nothing it reads changes.
  const scope = useMemo(() => {
    const answer = data as Partial<PluginRows>;
    return {
      rows: answer.rows ?? [],
      values: answer.values ?? {},
      strings: Object.fromEntries(
        Object.entries(plugin.strings).map(([key, text]) => [
          key,
          localized(text, i18n.language) ?? key,
        ])
      ),
      now: now ?? thisMinute(),
    };
  }, [data, plugin.strings, i18n.language, now]);

  const body = isLoading ? (
    <Skeleton className="h-full w-full" />
  ) : errorCode ? (
    <WidgetError code={errorCode} />
  ) : !result.template ? (
    <WidgetError code={WidgetErrorCode.TEMPLATE_INVALID} detail={result.errors[0]?.message} />
  ) : (
    renderTemplate(result.template, {
      data: scope,
      context: undefined,
      parts: {},
      communityId,
      elements: WIDGET_ELEMENT_COMPONENTS[view],
      classes: PLUGIN_CLASSES,
    })
  );

  return <TileFrame {...frame}>{body}</TileFrame>;
}

/** The tile's box: framed with its title, or bare where the canvas frames it. */
function TileFrame({
  type,
  title,
  className,
  chromeless,
  children,
}: Pick<WidgetTileProps, "type" | "title" | "className" | "chromeless"> & {
  children: React.ReactNode;
}) {
  const body = children;
  if (chromeless) {
    // No label here: the canvas's own <section> already names this region, and
    // a second label on a plain div would only add noise for a screen reader.
    //
    // Clipped, like the framed one below it. A tile is a fixed box on a grid
    // and what it holds is drawn by a renderer that cannot know how much room
    // it has — so the box is the last word on where its contents end. Each
    // renderer still fits itself first; this is what makes "it did not" a
    // clipped edge rather than a chart lying across the tile beside it.
    return (
      <div className={cn("h-full w-full overflow-hidden text-card-foreground", className)}>
        {body}
      </div>
    );
  }

  return (
    <section
      className={cn(
        "flex h-full w-full flex-col overflow-hidden rounded-lg border bg-card p-3 text-card-foreground",
        className
      )}
      aria-label={title ?? type}
    >
      {title && <h3 className="mb-2 shrink-0 truncate font-semibold text-sm">{title}</h3>}
      <div className="min-h-0 flex-1">{body}</div>
    </section>
  );
}
