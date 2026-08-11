import { Link } from "@tanstack/react-router";

import type { DashboardSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

interface DashboardCardProps {
  dashboard: DashboardSummary;
  initiativeName?: string;
  className?: string;
}

export const DashboardCard = ({ dashboard, initiativeName, className }: DashboardCardProps) => {
  const gp = useGuildPath();

  return (
    <Link
      to={gp(`/dashboards/${dashboard.id}`)}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <Card className="border-0 shadow-none">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="line-clamp-1 text-lg leading-tight">{dashboard.name}</CardTitle>
          </div>
          {dashboard.description && (
            <p className="line-clamp-2 text-muted-foreground text-sm">{dashboard.description}</p>
          )}
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          {initiativeName && (
            <div className="flex items-center gap-3 text-muted-foreground text-sm">
              <span className="truncate">{initiativeName}</span>
            </div>
          )}
          {dashboard.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {dashboard.tags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} nested />
              ))}
              {dashboard.tags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{dashboard.tags.length - 3}</span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
};
