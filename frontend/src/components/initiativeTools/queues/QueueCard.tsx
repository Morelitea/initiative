import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { type QueueSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface QueueCardProps {
  queue: QueueSummary;
  className?: string;
}

export const QueueCard = ({ queue, className }: QueueCardProps) => {
  const { t } = useTranslation("queues");
  const gp = useGuildPath();

  return (
    <Link
      to={gp(toolDetailRoute(Tool.queue, queue.initiative_id, queue.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <Card className="border-0 shadow-none">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="line-clamp-1 text-lg leading-tight">{queue.name}</CardTitle>
            <Badge variant={queue.is_active ? "default" : "secondary"} className="shrink-0">
              {queue.is_active ? t("active") : t("inactive")}
            </Badge>
          </div>
          {queue.description && (
            <p className="line-clamp-2 text-muted-foreground text-sm">{queue.description}</p>
          )}
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          <div className="flex items-center gap-3 text-muted-foreground text-sm">
            <Badge variant="outline">{t("itemCount", { count: queue.item_count })}</Badge>
            {queue.is_active && queue.current_round > 0 && (
              <span className="text-xs">{t("roundN", { count: queue.current_round })}</span>
            )}
          </div>
          <TagBadgeList tags={queue.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} nested />
        </CardContent>
      </Card>
    </Link>
  );
};
