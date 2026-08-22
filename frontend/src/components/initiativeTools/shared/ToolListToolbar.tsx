import type { LucideIcon } from "lucide-react";
import { ListChecks, MoreHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ToolFilterButton } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type ToolViewOption<V extends string> = {
  value: V;
  label: string;
  icon: LucideIcon;
};

type ToolListToolbarProps<V extends string> = {
  /** Leading control — the scope or status the list is showing. */
  leading?: ReactNode;
  /** Filter disclosure state, shared with the page's {@link ToolFilterPanel}.
   *  Omit on a list with no filters. */
  filters?: { open: boolean; onOpenChange: (open: boolean) => void; activeCount?: number };
  /** View-mode picker. Labels collapse to icons below `sm`. */
  view?: { value: V; onChange: (value: V) => void; options: ToolViewOption<V>[]; label: string };
  /** A view picker the caller owns — for a list whose views are already the
   *  content's own `Tabs`, which can't be nested. Replaces {@link view}. */
  viewControl?: ReactNode;
  /** Controls shown at every width, left of the filter button. For anything
   *  with no mobile equivalent elsewhere in the app (export, say) — unlike
   *  {@link actions}, which the bottom-nav add pill already covers. */
  trailing?: ReactNode;
  /** Buttons shown from `sm` up only. The bottom-nav add pill already runs the
   *  page's create action on mobile, so a create button here would be a second
   *  copy of it competing for the narrowest row in the app. */
  actions?: ReactNode;
  /** Items appended to the overflow menu — import, export, and anything else
   *  that would otherwise need its own row. */
  menuItems?: ReactNode;
  /** Adds "Select items" to the overflow menu, entering bulk-selection mode. */
  onEnterSelection?: () => void;
};

/**
 * The one control row a tool list gets: what's being shown on the left, and how
 * it's shown on the right. Everything secondary lives behind the filter button
 * or the overflow menu rather than claiming a row of its own — on a phone the
 * old four-row stack pushed the first card below the fold.
 *
 * Sticky below `sm` only. That's where it earns its keep (the mobile app header
 * is just the safe-area strip, so there is nothing to collide with), and it
 * keeps the row reachable forty cards into a scroll.
 */
export const ToolListToolbar = <V extends string>({
  leading,
  filters,
  view,
  viewControl,
  trailing,
  actions,
  menuItems,
  onEnterSelection,
}: ToolListToolbarProps<V>) => {
  const { t } = useTranslation("common");
  const hasMenu = Boolean(menuItems) || Boolean(onEnterSelection);

  return (
    <div
      className="sticky z-30 -mx-4 flex flex-wrap items-center gap-2 bg-background/90 px-4 py-2 backdrop-blur supports-backdrop-filter:bg-background/70 max-sm:border-b sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:backdrop-blur-none"
      style={{ top: "var(--safe-area-inset-top)" }}
    >
      {/* Two different ways to run out of room. Below `sm` the controls are
          icon-only and the leading group claims no width of its own (basis-0),
          so it scrolls sideways and the row stays one line. From `sm` up the
          labels are back and the row would rather wrap — the right-hand group
          drops to a second line instead of every control squeezing until its
          own label clips. `sm` is a *viewport* query, so a wide sidebar can
          leave a narrow column with the labels still on; the scroll container
          is the backstop for that, keeping the overflow off the page. */}
      {leading ? (
        <div className="-mx-1 min-w-0 overflow-x-auto px-1 [scrollbar-width:none] max-sm:grow max-sm:basis-0 [&::-webkit-scrollbar]:hidden">
          {leading}
        </div>
      ) : null}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        {actions ? <div className="hidden items-center gap-2 sm:flex">{actions}</div> : null}
        {trailing}
        {filters ? (
          <ToolFilterButton
            open={filters.open}
            onOpenChange={filters.onOpenChange}
            activeCount={filters.activeCount}
          />
        ) : null}
        {viewControl}
        {view ? (
          <Tabs
            value={view.value}
            onValueChange={(value) => view.onChange(value as V)}
            className="w-auto"
          >
            <TabsList aria-label={view.label} className="h-9">
              {view.options.map((option) => {
                const Icon = option.icon;
                return (
                  <TabsTrigger
                    key={option.value}
                    value={option.value}
                    aria-label={option.label}
                    className="inline-flex items-center gap-2 px-2.5 sm:px-3"
                  >
                    <Icon className="h-4 w-4" />
                    <span className="hidden sm:inline">{option.label}</span>
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </Tabs>
        ) : null}
        {hasMenu ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-9 w-9 p-0"
                aria-label={t("toolbar.moreActions")}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onEnterSelection ? (
                <DropdownMenuItem onSelect={onEnterSelection}>
                  <ListChecks className="h-4 w-4" />
                  {t("toolbar.selectItems")}
                </DropdownMenuItem>
              ) : null}
              {menuItems}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    </div>
  );
};
