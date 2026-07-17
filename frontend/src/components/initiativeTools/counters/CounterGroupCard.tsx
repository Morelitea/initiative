import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { CounterGroupSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

interface CounterGroupCardProps {
  group: CounterGroupSummary;
  initiativeName?: string;
  className?: string;
}

export const CounterGroupCard = ({ group, initiativeName, className }: CounterGroupCardProps) => {
  const { t } = useTranslation("counterGroups");
  const gp = useGuildPath();

  return (
    <Link
      to={gp(`/counter-groups/${group.id}`)}
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
            {initiativeName && <span className="truncate">{initiativeName}</span>}
            <Badge variant="outline">{t("counterCount", { count: group.counter_count })}</Badge>
          </div>
          {group.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {group.tags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
              {group.tags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{group.tags.length - 3}</span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
};
