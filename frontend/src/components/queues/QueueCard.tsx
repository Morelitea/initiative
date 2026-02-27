import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";
import type { QueueSummary } from "@/api/generated/initiativeAPI.schemas";

interface QueueCardProps {
  queue: QueueSummary;
  initiativeName?: string;
  className?: string;
}

export const QueueCard = ({ queue, initiativeName, className }: QueueCardProps) => {
  const { t } = useTranslation("queues");
  const gp = useGuildPath();

  return (
    <Link
      to={gp(`/queues/${queue.id}`)}
      className={cn(
        "group bg-card text-card-foreground hover:border-primary/50 block w-full overflow-hidden rounded-2xl border shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg",
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
            <p className="text-muted-foreground line-clamp-2 text-sm">{queue.description}</p>
          )}
        </CardHeader>
        <CardContent className="pt-0">
          <div className="text-muted-foreground flex items-center gap-3 text-sm">
            {initiativeName && <span className="truncate">{initiativeName}</span>}
            <Badge variant="outline">{t("itemCount", { count: queue.item_count })}</Badge>
            {queue.is_active && queue.current_round > 0 && (
              <span className="text-xs">{t("roundN", { count: queue.current_round })}</span>
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
};
