/**
 * One widget on a canvas: chrome, the sandbox call, and the failure path.
 *
 * The frame — border, title, loading state, error tile — is app code. A widget
 * contributes only what goes inside, and only as a validated scene. That split
 * is why a broken or hostile widget costs one tile: it cannot draw its own
 * frame, so it cannot pretend to be the app around it.
 */

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { WidgetConfig, WidgetData } from "@/lib/widgets/dataShapes";
import { WidgetErrorCode } from "@/lib/widgets/errors";
import { builtinWidgetSource } from "@/lib/widgets/registry";
import { renderWidget, type WidgetRenderOutcome } from "@/lib/widgets/runtime/host";

import { SceneRenderer } from "./scene/SceneRenderer";

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
  /** Draw this failure instead of running the widget — for the one case the
   *  module cannot speak to, its data never arriving. Running it over empty rows
   *  would show "nothing to display", which is a different and misleading claim
   *  from "the app behind this is not answering". */
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
}

type State = { status: "loading" } | { status: "done"; outcome: WidgetRenderOutcome };

export function WidgetTile({
  type,
  title,
  data,
  config,
  className,
  source,
  errorCode,
  isLoading,
  chromeless,
  now,
}: WidgetTileProps) {
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
    // it has already claimed "no data" for a widget whose app is down.
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
    renderWidget({ source: moduleSource, data, config: config ?? {}, now }).then((outcome) => {
      if (!cancelled) setState({ status: "done", outcome });
    });

    return () => {
      cancelled = true;
    };
  }, [type, data, config, source, now, errorCode, isLoading]);

  const body =
    isLoading || state.status === "loading" ? (
      <Skeleton className="h-full w-full" />
    ) : state.outcome.ok ? (
      <SceneRenderer node={state.outcome.spec.scene} />
    ) : (
      <WidgetError code={state.outcome.code} detail={state.outcome.detail} />
    );

  if (chromeless) {
    // No label here: the canvas's own <section> already names this region, and
    // a second label on a plain div would only add noise for a screen reader.
    return <div className={cn("h-full w-full text-card-foreground", className)}>{body}</div>;
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

function WidgetError({ code, detail }: { code: WidgetErrorCode; detail?: string }) {
  const { t } = useTranslation("dashboards");
  // Every failure has a localized line; the interpreter's own message is shown
  // underneath because a widget author debugging their module needs it, and it
  // is the only diagnostic that crosses the sandbox boundary.
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-1 p-2 text-center">
      <AlertTriangle className="h-4 w-4 text-muted-foreground" aria-hidden />
      <p className="text-muted-foreground text-sm">
        {t(`widgetError.${code}`, { defaultValue: t("widgetError.default") })}
      </p>
      {detail && (
        <p className="max-w-full truncate font-mono text-muted-foreground/70 text-xs">{detail}</p>
      )}
    </div>
  );
}
