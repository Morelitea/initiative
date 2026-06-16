import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { renderRecentIcon } from "@/lib/recentIcon";
import { type RecentKey, recentKeyMatches, recentRoute } from "@/lib/recentRoute";
import { cn } from "@/lib/utils";

interface RecentTabsBarProps {
  items?: RecentItemRead[];
  activeKey?: RecentKey | null;
  loading?: boolean;
  onClose: (item: RecentItemRead) => void;
}

/**
 * Sticky-header tabs bar for the 20 most-recently-opened guild-scoped items
 * (projects, documents, queues, counter groups). Replaces the projects-only
 * ``ProjectTabsBar``.
 */
export const RecentTabsBar = ({ items, activeKey, loading, onClose }: RecentTabsBarProps) => {
  const { t } = useTranslation("projects");

  if (!loading && (!items || items.length === 0)) {
    return null;
  }

  return (
    <ScrollArea className="h-12 pt-2.5">
      <div className="flex h-full items-end gap-2 px-4">
        {loading ? (
          <p className="py-3 text-muted-foreground text-xs">{t("tabsBar.loadingRecent")}</p>
        ) : (
          items?.map((item) => {
            const isActive = recentKeyMatches(activeKey ?? null, item);
            return (
              <div
                key={`${item.guild_id}-${item.entity_type}-${item.entity_id}`}
                className="flex items-center"
              >
                <Link
                  to={recentRoute(item)}
                  className={cn(
                    "group inline-flex items-center gap-2 rounded-t-md border border-transparent px-3 py-2 text-sm transition",
                    isActive
                      ? "border-border bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {renderRecentIcon(item)}
                  <span className="max-w-40 truncate">{item.name}</span>
                </Link>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="ml-1 h-7 w-7 text-muted-foreground hover:text-foreground"
                  onClick={(event) => {
                    event.preventDefault();
                    onClose(item);
                  }}
                  aria-label={t("tabsBar.closeItem", { name: item.name })}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })
        )}
      </div>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};
