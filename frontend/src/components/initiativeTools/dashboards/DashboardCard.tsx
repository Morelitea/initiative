import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { type DashboardSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDashboard, useWidgetCatalog } from "@/hooks/useDashboards";
import { useSeenOnScreen } from "@/hooks/useSeenOnScreen";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";
import { readConfig, readDefinition } from "@/lib/widgets/definition";

interface DashboardCardProps {
  dashboard: DashboardSummary;
  className?: string;
}

/** The width the dashboard is drawn at before it is shrunk into the card: a
 *  desktop's, so its widgets sit where their author put them. */
const PREVIEW_WIDTH = 1200;

/**
 * The dashboard itself, shrunk to the card.
 *
 * Read only once the card is on screen, through the same queries opening the
 * dashboard makes, so a long list costs what is scrolled past and a card opened
 * afterwards is already loaded. It is a picture: nothing in it can be clicked.
 */
const DashboardPreview = ({ dashboardId }: { dashboardId: number }) => {
  const { ref: box, seen: visible } = useSeenOnScreen<HTMLDivElement>();
  const [scale, setScale] = useState(0);

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const sized = new ResizeObserver(([entry]) => {
      if (entry) setScale(entry.contentRect.width / PREVIEW_WIDTH);
    });
    sized.observe(node);
    return () => sized.disconnect();
  }, [box]);

  const dashboardQuery = useDashboard(visible ? dashboardId : null);
  const catalogQuery = useWidgetCatalog({ enabled: visible });
  const dashboard = dashboardQuery.data;

  return (
    <div
      ref={box}
      aria-hidden
      inert
      className="pointer-events-none relative aspect-[16/9] overflow-hidden border-b bg-muted/40"
    >
      {dashboard && scale > 0 ? (
        <div
          className="absolute top-0 left-0 origin-top-left p-4"
          style={{ width: PREVIEW_WIDTH, transform: `scale(${scale})` }}
        >
          <DashboardCanvas
            definition={readDefinition(dashboard.definition)}
            config={readConfig(dashboard.config)}
            catalog={catalogQuery.data}
            initiativeId={dashboard.initiative_id}
            dashboardId={dashboard.id}
            canEdit={false}
            onLayoutChange={() => {}}
          />
        </div>
      ) : null}
    </div>
  );
};

export const DashboardCard = ({ dashboard, className }: DashboardCardProps) => {
  const gp = useCommunityPath();

  return (
    // The link is the title, stretched over the card, rather than the card:
    // the preview holds the dashboard's own links, and a link cannot sit
    // inside another.
    <div
      className={cn(
        "group relative w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <DashboardPreview dashboardId={dashboard.id} />
      <Card className="border-0 shadow-none">
        <CardHeader className="pb-2">
          <CardTitle className="line-clamp-1 text-lg leading-tight">
            <Link
              to={gp(toolDetailRoute(Tool.dashboard, dashboard.initiative_id, dashboard.id))}
              className="after:absolute after:inset-0"
            >
              {dashboard.name}
            </Link>
          </CardTitle>
          {dashboard.description && (
            <p className="line-clamp-2 text-muted-foreground text-sm">{dashboard.description}</p>
          )}
        </CardHeader>
        <CardContent className="relative z-10 space-y-2 pt-0">
          <TagBadgeList tags={dashboard.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} />
        </CardContent>
      </Card>
    </div>
  );
};
