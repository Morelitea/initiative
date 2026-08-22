import { Filter, FilterX } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useIsCompactViewport } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";

type ToolFilterButtonProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** How many filters are currently narrowing the list. Badges the button so
   *  an active filter announces itself while the panel is closed. */
  activeCount?: number;
};

/**
 * The filter affordance in a list toolbar: one icon button carrying the count
 * of active filters. Pair it with a {@link ToolFilterPanel} driven by the same
 * open state — the button toggles, the panel holds the fields.
 */
export const ToolFilterButton = ({
  open,
  onOpenChange,
  activeCount = 0,
}: ToolFilterButtonProps) => {
  const { t } = useTranslation("common");

  return (
    <Button
      variant={open || activeCount > 0 ? "secondary" : "outline"}
      size="sm"
      className="h-9 gap-2"
      aria-expanded={open}
      aria-label={
        activeCount > 0 ? t("toolbar.filtersActive", { count: activeCount }) : t("toolbar.filters")
      }
      onClick={() => onOpenChange(!open)}
    >
      <Filter className="h-4 w-4" />
      <span className="hidden sm:inline">{t("toolbar.filters")}</span>
      {activeCount > 0 ? (
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 font-medium text-[11px] text-primary-foreground tabular-nums">
          {activeCount}
        </span>
      ) : null}
    </Button>
  );
};

type ToolFilterPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Heading for the mobile sheet. */
  title: string;
  /** Resets every filter this panel owns; omitted when there is nothing to
   *  clear (e.g. a list whose only filter is a search box). */
  onClear?: () => void;
  /** How many filters are currently narrowing the list. Only used to tell
   *  "Clear all" whether it has anything to do. */
  activeCount?: number;
  children: ReactNode;
};

/**
 * A tool list's filter fields. From `sm` up they sit inline under the toolbar,
 * the way they always have. Below it they move into a bottom sheet: the mobile
 * form is a column of full-width fields, and inline it pushed the list itself
 * off the screen.
 *
 * Filter values are owned by the calling page, so the fields themselves are
 * free to move between the two layouts.
 */
export const ToolFilterPanel = ({
  open,
  onOpenChange,
  title,
  onClear,
  activeCount = 0,
  children,
}: ToolFilterPanelProps) => {
  const { t } = useTranslation("common");
  const isCompact = useIsCompactViewport();

  const fields = (footer?: ReactNode) => (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-md border border-muted bg-background/40 p-3",
        "max-sm:border-0 max-sm:bg-transparent max-sm:p-0"
      )}
    >
      {children}
      {footer}
    </div>
  );

  // Disabled rather than hidden while nothing is set: the control keeps its
  // place, so the panel doesn't reflow the moment a filter is applied.
  const clearButton = onClear ? (
    <Button variant="ghost" size="sm" onClick={onClear} disabled={activeCount === 0}>
      <FilterX className="h-4 w-4" />
      {t("clearAll")}
    </Button>
  ) : null;

  if (isCompact) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="bottom" className="max-h-[85svh] overflow-y-auto">
          <SheetHeader className="mb-4 text-left">
            <SheetTitle>{title}</SheetTitle>
          </SheetHeader>
          {fields()}
          <div
            className="mt-6 flex gap-2"
            style={{ paddingBottom: "var(--safe-area-inset-bottom)" }}
          >
            {onClear ? (
              <Button
                variant="outline"
                className="flex-1"
                onClick={onClear}
                disabled={activeCount === 0}
              >
                <FilterX className="h-4 w-4" />
                {t("clearAll")}
              </Button>
            ) : null}
            <Button className="flex-1" onClick={() => onOpenChange(false)}>
              {t("toolbar.applyFilters")}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    );
  }

  // Mounted either way, hidden when closed — matches how the inline panel has
  // always behaved, so a re-open costs nothing.
  return (
    <div className={open ? undefined : "hidden"}>
      {fields(
        clearButton ? (
          <div className="flex justify-end border-muted border-t pt-3">{clearButton}</div>
        ) : null
      )}
    </div>
  );
};
