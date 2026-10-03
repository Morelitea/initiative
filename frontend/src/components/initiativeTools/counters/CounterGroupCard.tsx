import { Link } from "@tanstack/react-router";

import { type CounterGroupSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCounterGroup } from "@/hooks/useCounters";
import { useSeenOnScreen } from "@/hooks/useSeenOnScreen";
import { useCommunityPath } from "@/lib/communityUrl";
import { getContrastingTextColor } from "@/lib/counter-color";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface CounterGroupCardProps {
  group: CounterGroupSummary;
  className?: string;
}

/** Counters shown on the card before the rest are left to the group. */
const PREVIEW_COUNTERS = 4;

/**
 * The group's first few counters and where they stand, read once the card is
 * on screen through the query opening the group makes.
 */
const CounterGroupPreview = ({ groupId }: { groupId: number }) => {
  const { ref, seen } = useSeenOnScreen<HTMLDivElement>();
  const counters = useCounterGroup(seen ? groupId : null).data?.counters ?? [];

  return (
    <div
      ref={ref}
      aria-hidden
      className="grid min-h-24 grid-cols-2 gap-1.5 border-b bg-muted/40 p-3"
    >
      {counters.slice(0, PREVIEW_COUNTERS).map((counter) => {
        // The colours the counter wears on its own page.
        return (
          <div
            key={counter.id}
            className="flex min-w-0 flex-col justify-between rounded-lg border px-2.5 py-1.5"
            style={{
              backgroundColor: counter.color ?? "hsl(var(--card))",
              color: getContrastingTextColor(counter.color) ?? "hsl(var(--card-foreground))",
            }}
          >
            <span className="truncate text-xs opacity-80">{counter.name}</span>
            <span className="font-semibold text-xl tabular-nums leading-tight">
              {Number(counter.count).toLocaleString()}
            </span>
          </div>
        );
      })}
    </div>
  );
};

export const CounterGroupCard = ({ group, className }: CounterGroupCardProps) => {
  const gp = useCommunityPath();

  return (
    <Link
      to={gp(toolDetailRoute(Tool.counter_group, group.initiative_id, group.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <CounterGroupPreview groupId={group.id} />
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
          <TagBadgeList tags={group.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} nested />
        </CardContent>
      </Card>
    </Link>
  );
};
