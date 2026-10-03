import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { type QueueSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useQueue } from "@/hooks/useQueues";
import { useSeenOnScreen } from "@/hooks/useSeenOnScreen";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface QueueCardProps {
  queue: QueueSummary;
  className?: string;
}

/** Turns shown on the card: whoever is up, and the next ones after them. */
const PREVIEW_TURNS = 3;

/**
 * Whose turn it is and who follows, in the order the queue runs, read once the
 * card is on screen through the query opening the queue makes. A queue not
 * running shows its order from the top.
 */
const QueuePreview = ({ queueId }: { queueId: number }) => {
  const { ref, seen } = useSeenOnScreen<HTMLDivElement>();
  const queue = useQueue(seen ? queueId : null).data;
  const order = (queue?.items ?? [])
    .filter((item) => item.is_visible && item.held_at_round === null)
    .sort((a, b) => b.position - a.position);
  const current = queue?.is_active ? queue.current_item : null;
  const start = current
    ? Math.max(
        0,
        order.findIndex((item) => item.id === current.id)
      )
    : 0;
  const turns = [...order.slice(start), ...order.slice(0, start)].slice(0, PREVIEW_TURNS);

  return (
    <div ref={ref} aria-hidden className="min-h-24 space-y-1 border-b bg-muted/40 p-3">
      {turns.map((item, index) => {
        const up = current !== null && index === 0;
        return (
          <div
            key={item.id}
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-1 text-sm",
              up ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground"
            )}
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: item.color ?? "currentColor" }}
            />
            <span className="truncate">{item.label}</span>
          </div>
        );
      })}
    </div>
  );
};

export const QueueCard = ({ queue, className }: QueueCardProps) => {
  const { t } = useTranslation("queues");
  const gp = useCommunityPath();

  return (
    <Link
      to={gp(toolDetailRoute(Tool.queue, queue.initiative_id, queue.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <QueuePreview queueId={queue.id} />
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
          {queue.is_active && queue.current_round > 0 && (
            <p className="text-muted-foreground text-xs">
              {t("roundN", { count: queue.current_round })}
            </p>
          )}
          <TagBadgeList tags={queue.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} nested />
        </CardContent>
      </Card>
    </Link>
  );
};
