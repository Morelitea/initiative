/**
 * One widget on a canvas: chrome, drawing the widget, and the failure path.
 *
 * The frame — border, title, loading state, error tile — is app code. A widget
 * contributes only what goes inside. A built-in is our own code and template;
 * a plug-in's module still runs in the sandbox and returns a validated scene.
 * That split is why a broken or hostile widget costs one tile: it cannot draw
 * its own frame, so it cannot pretend to be the app around it.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { renderTemplate } from "@/lib/templates/render";
import { cn } from "@/lib/utils";
import type { BuiltinWidget } from "@/lib/widgets/builtins/builtin";
import type { TabularData, WidgetConfig, WidgetData } from "@/lib/widgets/dataShapes";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import { builtinWidget, builtinWidgetSource } from "@/lib/widgets/registry";
import { renderWidget, type WidgetRenderOutcome } from "@/lib/widgets/runtime/host";

import { SceneRenderer } from "./scene/SceneRenderer";
import { SceneTableView } from "./scene/SceneTableView";
import { WIDGET_ELEMENT_COMPONENTS } from "./scene/widgetElements";
import { WidgetError } from "./WidgetError";

export interface WidgetTileProps {
  /** Widget primitive from the definition — the key into the module registry. */
  type: string;
  title?: string;
  data: WidgetData;
  config?: WidgetConfig;
  className?: string;
  /** Overrides the registry lookup. This is the seam a marketplace listing's
   *  own widget module arrives through; it runs the same way ours does. */
  source?: string;
  /** Which of the data's columns fill each of the widget's slots. Resolved by
   *  the caller, which is the only place that has the widget's declared shape
   *  and the author's overrides together. */
  slots?: Record<string, number[]>;
  /** Draw this failure instead of running the widget — for the one case the
   *  module cannot speak to, its data never arriving. Running it over empty rows
   *  would show "nothing to display", which is a different and misleading claim
   *  from "the plug-in behind this is not answering". */
  errorCode?: WidgetErrorCode;
  /** The binding's own fetch is still in flight. Shown as the same skeleton the
   *  sandbox call uses, so a widget does not flash empty then populate. */
  isLoading?: boolean;
  /** Drop the border and title — the canvas frames its own widgets, and two
   *  nested frames read as a bug. The scene still cannot escape its box. */
  chromeless?: boolean;
  /** Freeze the widget's clock. Previews render frozen sample data and pass
   *  the samples' own anchor here, so a clock-reading widget draws the same
   *  picture every time; live tiles omit it and get the real minute. */
  now?: number;
  /** Draw the scene, or the same scene's numbers as a table. The widget runs
   *  identically either way — the table is derived from what it returned, not
   *  requested from it — so nothing about a widget changes when a reader
   *  switches, and a widget cannot tell which one it is being read in. */
  view?: "scene" | "table";
}

type State = { status: "loading" } | { status: "done"; outcome: WidgetRenderOutcome };

/** The minute a widget is drawn for: rounded, so a clock-reading widget draws
 *  the same picture all minute and its answers can be reused. */
const thisMinute = () => Math.floor(Date.now() / 60_000) * 60_000;

export function WidgetTile(props: WidgetTileProps) {
  const builtin = props.source ? undefined : builtinWidget(props.type);
  return builtin ? <BuiltinTile {...props} widget={builtin} /> : <ModuleTile {...props} />;
}

/**
 * A built-in: its code works out a model from the data, and its template draws
 * it with the widget elements. Nothing runs in the sandbox.
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

/** A plug-in's widget: its module runs in the sandbox and returns a scene. */
function ModuleTile({
  type,
  title,
  data,
  config,
  slots,
  className,
  source,
  errorCode,
  isLoading,
  chromeless,
  now,
  view = "scene",
}: WidgetTileProps) {
  const { i18n } = useTranslation();
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    // A widget whose data could not be fetched is not run at all: there is
    // nothing for it to draw, and the reason belongs to the host.
    if (errorCode) {
      setState({ status: "done", outcome: { ok: false, code: errorCode } });
      return;
    }
    // Nor is it run while its data is still on the way. The tile is already
    // showing a skeleton, so an early run draws nothing anyone sees — it just
    // spends a sandbox call per widget per mount, and if the fetch then fails
    // it has already claimed "no data" for a widget whose plug-in is down.
    if (isLoading) return;

    const moduleSource = source ?? builtinWidgetSource(type);

    if (!moduleSource) {
      setState({
        status: "done",
        outcome: { ok: false, code: WidgetErrorCode.TYPE_UNSUPPORTED },
      });
      return;
    }

    // Deliberately not resetting to "loading" first: a re-render is fast, and
    // blanking to a skeleton every time the data changes makes a live tile
    // flicker on each refetch. The scene already on screen stays until the new
    // one is ready.
    // The viewer's language goes in with the data: a widget's column headings
    // and empty states are its own words, so it is the only thing that can put
    // them in the right language.
    renderWidget({
      source: moduleSource,
      data,
      config: config ?? {},
      now,
      locale: i18n.language,
      slots,
    }).then((outcome) => {
      if (!cancelled) setState({ status: "done", outcome });
    });

    return () => {
      cancelled = true;
    };
  }, [type, data, config, source, now, errorCode, isLoading, i18n.language, slots]);

  const body =
    isLoading || state.status === "loading" ? (
      <Skeleton className="h-full w-full" />
    ) : state.outcome.ok ? (
      view === "table" ? (
        <SceneTableView node={state.outcome.spec.scene} />
      ) : (
        <SceneRenderer node={state.outcome.spec.scene} />
      )
    ) : (
      <WidgetError code={state.outcome.code} detail={state.outcome.detail} />
    );

  return (
    <TileFrame type={type} title={title} className={className} chromeless={chromeless}>
      {body}
    </TileFrame>
  );
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
