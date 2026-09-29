import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { type CounterGroupSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface CounterGroupCardProps {
  group: CounterGroupSummary;
  className?: string;
}

export const CounterGroupCard = ({ group, className }: CounterGroupCardProps) => {
  const { t } = useTranslation("counterGroups");
  const gp = useGuildPath();

  return (
    <Link
      to={gp(toolDetailRoute(Tool.counter_group, group.initiative_id, group.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <Card className="border-0 shadow-none">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="line-clamp-1 text-lg leading-tight">{group.name}</CardTitle>
          </div>
          {group.description && (
            <p className="line-clamp-2 text-muted-foreground text-sm">{group.description}</p>
          )}
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          <div className="flex items-center gap-3 text-muted-foreground text-sm">
            <Badge variant="outline">{t("counterCount", { count: group.counter_count })}</Badge>
          </div>
          <TagBadgeList tags={group.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} nested />
        </CardContent>
      </Card>
    </Link>
  );
};
