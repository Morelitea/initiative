/**
 * Widget gallery — every built-in, drawn through the real pipeline.
 *
 * Each tile fetches nothing: it hands a fixture to the same sandbox, validator,
 * and renderer a live dashboard uses, so what you see here is exactly what the
 * canvas will draw once the fetchers land (Phase 2b). It is also the fastest
 * way to see a SceneSpec change across all seven widgets at once.
 *
 * Note where the strings come from. This page's own chrome is ours and lives in
 * `dashboards.json`; every widget *name* and option label comes from the widget
 * module itself. That split is the point — an installed listing has to be able
 * to name itself without an app release, so the built-ins are read the same way.
 *
 * Development surface, not a product page: unlisted, and fixed-size because the
 * drag/resize canvas is the next phase's work.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { WidgetTile } from "@/components/initiativeTools/dashboards/WidgetTile";
import { Button } from "@/components/ui/button";
import { useWidgetMeta } from "@/hooks/useWidgetMeta";
import { ALL_FIXTURES, fixtureFor, SOURCES_BY_WIDGET } from "@/lib/widgets/__fixtures__/widgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import { BUILTIN_WIDGET_TYPES } from "@/lib/widgets/registry";
import { localized } from "@/lib/widgets/widgetMeta";

/** Widget modules that misbehave in each way the runtime bounds, so the error
 *  path is visible rather than only asserted in tests. The label keys are ours
 *  — these are our test fixtures, not widgets anyone ships. */
const HOSTILE_WIDGETS = [
  { key: "infiniteLoop", source: "function render() { while (true) {} }" },
  {
    key: "runawayAllocation",
    source: "function render() { const a = []; while (true) a.push(new Array(9999).fill('x')); }",
  },
  { key: "throws", source: "function render() { throw new Error('boom'); }" },
  { key: "noRenderExport", source: "const notRender = 1;" },
  {
    key: "triesToFetch",
    source: "function render() { return fetch('https://example.test'); }",
  },
  {
    key: "invalidScene",
    source: 'function render() { return { v: 1, scene: { kind: "iframe" } }; }',
  },
] as const;

const MARKS = [null, "bar", "line", "area", "pie"] as const;

export function WidgetGalleryPage() {
  const { t, i18n } = useTranslation("dashboards");
  const [markOverride, setMarkOverride] = useState<string | null>(null);

  // The chart widget declares its own mark labels, so the control below reads
  // them from the module rather than from our locale files.
  const { meta: chartMeta } = useWidgetMeta("chart");

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
        <h1 className="font-semibold text-3xl tracking-tight">{t("gallery.title")}</h1>
        <p className="text-muted-foreground text-sm">
          {t("gallery.description", {
            combinations: tiles.length,
            widgets: BUILTIN_WIDGET_TYPES.length,
            sources: ALL_FIXTURES.length,
          })}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-sm">
          {localized(chartMeta?.options?.mark?.label, i18n.language) ?? t("gallery.markLabel")}
        </span>
        {MARKS.map((mark) => (
          <MarkButton
            key={mark ?? "default"}
            mark={mark}
            active={markOverride === mark}
            onSelect={setMarkOverride}
          />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {tiles.map(({ key, type, source }) => (
          <GalleryTile key={key} type={type} source={source} markOverride={markOverride} />
        ))}
      </div>

      <div className="space-y-1 pt-4">
        <h2 className="font-semibold text-xl tracking-tight">{t("gallery.failureModes")}</h2>
        <p className="text-muted-foreground text-sm">{t("gallery.failureModesDescription")}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {HOSTILE_WIDGETS.map((widget) => (
          <div key={widget.key} className="h-40">
            <WidgetTile
              type="kpi"
              title={t(`gallery.failure.${widget.key}` as const)}
              source={widget.source}
              data={fixtureFor("task_counts")}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/** One combination. Titled from the widget's own name plus our label for the
 *  binding source — the source names our endpoints, so that half is ours. */
function GalleryTile({
  type,
  source,
  markOverride,
}: {
  type: string;
  source: WidgetSource;
  markOverride: string | null;
}) {
  const { t } = useTranslation("dashboards");
  const { name } = useWidgetMeta(type);

  return (
    <div className="h-64">
      <WidgetTile
        type={type}
        title={t("gallery.tileTitle", {
          widget: name,
          source: t(`bindingSource.${source}` as const),
        })}
        data={fixtureFor(source, type)}
        config={type === "chart" && markOverride ? { mark: markOverride } : undefined}
      />
    </div>
  );
}

function MarkButton({
  mark,
  active,
  onSelect,
}: {
  mark: string | null;
  active: boolean;
  onSelect: (mark: string | null) => void;
}) {
  const { t, i18n } = useTranslation("dashboards");
  const { meta } = useWidgetMeta("chart");
  const label = mark
    ? (localized(meta?.options?.mark?.values?.[mark], i18n.language) ?? mark)
    : t("gallery.markDefault");

  return (
    <Button size="sm" variant={active ? "default" : "outline"} onClick={() => onSelect(mark)}>
      {label}
    </Button>
  );
}
