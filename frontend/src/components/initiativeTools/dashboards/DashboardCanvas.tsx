/**
 * The canvas — many widgets, freely arranged.
 *
 * A 12-column grid where each widget carries its own `{x, y, w, h}`. Layout is
 * part of the definition, so arranging a dashboard is *authoring*: it writes the
 * dashboard's own row and takes DAC write, which is why a viewer without it gets
 * a static grid rather than a disabled-looking one.
 *
 * Below the grid's breakpoint the canvas stacks into a single column, view-only.
 * Drag and resize are desktop authoring affordances; fighting a touch target for
 * them would trade a real interaction for a fiddly one.
 */

import { useMemo, useState } from "react";
import {
  type Layout,
  type LayoutItem,
  ResponsiveGridLayout,
  type ResponsiveLayouts,
  useContainerWidth,
  verticalCompactor,
} from "react-grid-layout";
import { useTranslation } from "react-i18next";

import type { WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import { cn } from "@/lib/utils";
import {
  applyLayout,
  catalogEntry,
  type DashboardConfig,
  type DashboardDefinition,
  effectiveBinding,
  GRID_COLUMNS,
} from "@/lib/widgets/definition";

import { DashboardWidget } from "./DashboardWidget";

// v2 folds the resize-handle styles into its own stylesheet; the separate
// react-resizable CSS the v1 docs pair this with no longer exists.
import "react-grid-layout/css/styles.css";

// v2 replaced the WidthProvider HOC with a hook, so the measured element is
// ours and the grid is told the width explicitly.
const ROW_HEIGHT = 56;
const MARGIN: [number, number] = [12, 12];

/** One column below `md`, so a phone reads the canvas top to bottom in layout
 *  order instead of squeezing a Gantt into a quarter of the screen. */
const BREAKPOINTS = { lg: 1024, md: 768, xs: 0 };
const COLS = { lg: GRID_COLUMNS, md: GRID_COLUMNS, xs: 1 };

export interface DashboardCanvasProps {
  definition: DashboardDefinition;
  config: DashboardConfig;
  catalog: WidgetCatalog | undefined;
  /** DAC write on this dashboard. Arranging is authoring. */
  canEdit: boolean;
  onLayoutChange: (next: DashboardDefinition) => void;
  onConfigureWidget?: (widgetId: string) => void;
  onRemoveWidget?: (widgetId: string) => void;
}

export function DashboardCanvas({
  definition,
  config,
  catalog,
  canEdit,
  onLayoutChange,
  onConfigureWidget,
  onRemoveWidget,
}: DashboardCanvasProps) {
  const { t } = useTranslation("dashboards");
  const [dragging, setDragging] = useState(false);
  const { width, mounted, containerRef } = useContainerWidth();

  // RGL fires onLayoutChange on mount as well as on every settle. Comparing
  // against the definition we are *currently rendering* is what tells the two
  // apart: opening a dashboard you can edit must not write its row.
  const placed = JSON.stringify(definition.widgets.map((widget) => widget.grid));

  const layouts = useMemo(() => {
    const items: LayoutItem[] = definition.widgets.map((widget) => {
      const entry = catalogEntry(catalog, widget.type);
      return {
        i: widget.id,
        x: widget.grid.x,
        y: widget.grid.y,
        w: widget.grid.w,
        h: widget.grid.h,
        minW: entry?.min_w ?? 1,
        minH: entry?.min_h ?? 1,
        static: !canEdit,
      };
    });
    // The stacked breakpoint is derived, not authored: full width, in order.
    const stacked: LayoutItem[] = definition.widgets.map((widget, index) => ({
      i: widget.id,
      x: 0,
      y: index,
      w: 1,
      h: widget.grid.h,
      static: true,
    }));
    return { lg: items, md: items, xs: stacked };
  }, [definition.widgets, catalog, canEdit]);

  const handleLayoutChange = (current: Layout, all: ResponsiveLayouts<string>) => {
    if (!canEdit) return;
    // Only the authored breakpoints write back; the stacked one is derived, so
    // reading it back would flatten everyone's layout to one column.
    const source = all.lg ?? current;
    const next = applyLayout(definition, catalog, [...source]);
    if (JSON.stringify(next.widgets.map((widget) => widget.grid)) === placed) return;
    onLayoutChange(next);
  };

  if (!definition.widgets.length) {
    return (
      <div ref={containerRef} className="rounded-lg border border-dashed p-10 text-center">
        <p className="font-medium text-sm">{t("canvas.empty")}</p>
        <p className="mt-1 text-muted-foreground text-sm">
          {canEdit ? t("canvas.emptyHint") : t("canvas.emptyReadOnly")}
        </p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full">
      {/* Nothing is placed until the container has a width, or every widget
          would mount at the fallback size and then jump. */}
      {mounted && (
        <ResponsiveGridLayout
          width={width}
          className={cn("-m-3", dragging && "select-none")}
          layouts={layouts}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          rowHeight={ROW_HEIGHT}
          margin={MARGIN}
          containerPadding={MARGIN}
          // v2 groups these; the handle selector is what keeps a widget's own
          // content from becoming a drag surface.
          dragConfig={{ enabled: canEdit, handle: "[data-widget-handle]" }}
          resizeConfig={{ enabled: canEdit }}
          onDragStart={() => setDragging(true)}
          onDragStop={() => setDragging(false)}
          onResizeStart={() => setDragging(true)}
          onResizeStop={() => setDragging(false)}
          onLayoutChange={handleLayoutChange}
          // Widgets settle upward into free space and never overlap.
          compactor={verticalCompactor}
        >
          {definition.widgets.map((widget) => (
            <div key={widget.id}>
              <DashboardWidget
                widget={widget}
                binding={effectiveBinding(widget, config)}
                canEdit={canEdit}
                onConfigure={onConfigureWidget}
                onRemove={onRemoveWidget}
              />
            </div>
          ))}
        </ResponsiveGridLayout>
      )}
    </div>
  );
}
