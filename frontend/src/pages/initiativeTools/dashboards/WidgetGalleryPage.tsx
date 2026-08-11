/**
 * Widget gallery — every built-in, drawn through the real pipeline.
 *
 * Each tile below fetches nothing: it hands a fixture to the same sandbox,
 * validator, and renderer a live dashboard uses, so what you see here is
 * exactly what the canvas will draw once the fetchers land (Phase 2b). It is
 * also the fastest way to see a SceneSpec change across all seven widgets at
 * once.
 *
 * Development surface, not a product page — it is unlisted, carries no
 * translations, and renders at fixed sizes because the drag/resize canvas is
 * the next phase's work.
 */

import { useMemo, useState } from "react";

import { WidgetTile } from "@/components/initiativeTools/dashboards/WidgetTile";
import { Button } from "@/components/ui/button";
import { ALL_FIXTURES, fixtureFor, SOURCES_BY_WIDGET } from "@/lib/widgets/__fixtures__/widgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import { BUILTIN_WIDGET_TYPES } from "@/lib/widgets/registry";

/** A widget module that misbehaves in each of the ways the runtime bounds, so
 *  the error path is visible rather than only asserted in tests. */
const HOSTILE_WIDGETS: { label: string; source: string }[] = [
  { label: "Infinite loop", source: "function render() { while (true) {} }" },
  {
    label: "Runaway allocation",
    source: "function render() { const a = []; while (true) a.push(new Array(9999).fill('x')); }",
  },
  { label: "Throws", source: "function render() { throw new Error('boom'); }" },
  { label: "No render export", source: "const notRender = 1;" },
  {
    label: "Tries to fetch",
    source: "function render() { return fetch('https://example.test'); }",
  },
  {
    label: "Invalid scene",
    source: 'function render() { return { v: 1, scene: { kind: "iframe" } }; }',
  },
];

export function WidgetGalleryPage() {
  const [markOverride, setMarkOverride] = useState<string | null>(null);

  const tiles = useMemo(
    () =>
      BUILTIN_WIDGET_TYPES.flatMap((type) =>
        (SOURCES_BY_WIDGET[type] ?? []).map((source: WidgetSource) => ({
          key: `${type}:${source}`,
          type,
          source,
        }))
      ),
    []
  );

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">Widget gallery</h1>
        <p className="text-muted-foreground text-sm">
          Every built-in widget, run in the sandbox against fixture data. {tiles.length}{" "}
          combinations across {BUILTIN_WIDGET_TYPES.length} widgets and {ALL_FIXTURES.length}{" "}
          sources.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-sm">Chart mark:</span>
        {[null, "bar", "line", "area", "pie"].map((mark) => (
          <Button
            key={mark ?? "default"}
            size="sm"
            variant={markOverride === mark ? "default" : "outline"}
            onClick={() => setMarkOverride(mark)}
          >
            {mark ?? "default"}
          </Button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {tiles.map(({ key, type, source }) => (
          <div key={key} className="h-64">
            <WidgetTile
              type={type}
              title={`${type} — ${source}`}
              data={fixtureFor(source, type)}
              config={type === "chart" && markOverride ? { mark: markOverride } : undefined}
            />
          </div>
        ))}
      </div>

      <div className="space-y-1 pt-4">
        <h2 className="font-semibold text-xl tracking-tight">Failure modes</h2>
        <p className="text-muted-foreground text-sm">
          Each tile below runs a deliberately broken widget. They should each show an error tile —
          and the page around them should stay responsive throughout.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {HOSTILE_WIDGETS.map((widget) => (
          <div key={widget.label} className="h-40">
            <WidgetTile
              type="kpi"
              title={widget.label}
              source={widget.source}
              data={fixtureFor("task_counts")}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
