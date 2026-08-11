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

/**
 * Two breakpoints, because there are only two *kinds* of layout: the authored
 * one and the derived stack. A third that also held 12 columns would be a
 * second place the same arrangement lives, and telling them apart in the
 * change callback is exactly where that goes wrong.
 *
 * Below the threshold a phone reads the canvas top to bottom in layout order
 * rather than squeezing a Gantt into a quarter of the screen.
 */
const STACKED = "xs";
const AUTHORED = "lg";
const STACK_BELOW = 768;
const BREAKPOINTS = { [AUTHORED]: STACK_BELOW, [STACKED]: 0 };
const COLS = { [AUTHORED]: GRID_COLUMNS, [STACKED]: 1 };

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

  // Whether the user is looking at the authored layout or the derived stack.
  // Derived from the measured width rather than tracked separately, because
  // that is the same number the grid picks its own breakpoint from — so the
  // two can never disagree, including before the first measurement lands.
  const authoring = width >= STACK_BELOW;

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
    return { [AUTHORED]: items, [STACKED]: stacked };
  }, [definition.widgets, catalog, canEdit]);

  const handleLayoutChange = (current: Layout) => {
    if (!canEdit) return;
    // The stacked layout is derived, not authored — writing it back would
    // flatten everyone's arrangement to one column. `current` is whichever
    // breakpoint the user is actually on, so it is the only correct source:
    // reading a named breakpoint out of `all` would take a stale copy of the
    // one they are not editing.
    if (!authoring) return;
    const next = applyLayout(definition, catalog, [...current]);
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
