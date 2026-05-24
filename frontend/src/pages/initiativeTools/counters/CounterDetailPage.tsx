import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  Minus,
  MoreVertical,
  Pencil,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";
import { type TouchEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CounterRead } from "@/api/generated/initiativeAPI.schemas";
import { CounterFormDialog } from "@/components/initiativeTools/counters/CounterFormDialog";
import { CounterNumberView } from "@/components/initiativeTools/counters/views/CounterNumberView";
import { CounterProgressBarView } from "@/components/initiativeTools/counters/views/CounterProgressBarView";
import { CounterSegmentedClockView } from "@/components/initiativeTools/counters/views/CounterSegmentedClockView";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCounterGroupRealtime } from "@/hooks/useCounterGroupRealtime";
import {
  useCounterGroup,
  useResetCounter,
  useSetCount,
  useSteppedCount,
} from "@/hooks/useCounters";
import { getContrastingTextColor } from "@/lib/counter-color";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

const SWIPE_THRESHOLD_PX = 60;

export function CounterDetailPage() {
  const { t } = useTranslation(["counters", "common"]);
  const navigate = useNavigate();
  const gp = useGuildPath();
  const {
    guildId,
    groupId: groupIdParam,
    counterId: counterIdParam,
  } = useParams({
    strict: false,
  }) as { guildId?: string; groupId?: string; counterId?: string };

  const groupId = groupIdParam ? Number(groupIdParam) : null;
  const counterId = counterIdParam ? Number(counterIdParam) : null;

  const groupQuery = useCounterGroup(groupId);
  useCounterGroupRealtime(groupId);

  const setCount = useSetCount(groupId ?? 0);
  const stepper = useSteppedCount(groupId ?? 0);
  const resetOne = useResetCounter(groupId ?? 0);

  const [editing, setEditing] = useState<CounterRead | null>(null);
  const [touchStartX, setTouchStartX] = useState<number | null>(null);
  const [touchStartY, setTouchStartY] = useState<number | null>(null);

  const group = groupQuery.data;
  const counters = useMemo(() => {
    const list = group?.counters ?? [];
    return [...list].sort((a, b) => Number(a.position) - Number(b.position));
  }, [group?.counters]);

  const currentIndex = useMemo(
    () => counters.findIndex((c) => c.id === counterId),
    [counters, counterId]
  );
  const counter = currentIndex >= 0 ? counters[currentIndex] : null;

  const canWrite = group?.my_permission_level === "owner" || group?.my_permission_level === "write";

  const goToCounter = (index: number) => {
    if (counters.length === 0 || !guildId || !groupId) return;
    const wrapped = ((index % counters.length) + counters.length) % counters.length;
    const next = counters[wrapped];
    if (!next) return;
    navigate({
      to: "/g/$guildId/counter-groups/$groupId/counter/$counterId",
      params: {
        guildId,
        groupId: String(groupId),
        counterId: String(next.id),
      },
      replace: true,
    });
  };

  const handleTouchStart = (event: TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    if (!touch) return;
    setTouchStartX(touch.clientX);
    setTouchStartY(touch.clientY);
  };

  const handleTouchEnd = (event: TouchEvent<HTMLDivElement>) => {
    if (touchStartX === null || touchStartY === null) return;
    const touch = event.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - touchStartX;
    const dy = touch.clientY - touchStartY;
    setTouchStartX(null);
    setTouchStartY(null);
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy)) return;
    goToCounter(currentIndex + (dx < 0 ? 1 : -1));
  };

  if (groupId === null || counterId === null) return null;

  if (groupQuery.isLoading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loadingGroup")}
        </div>
      </div>
    );
  }

  if (groupQuery.isError || !group) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-background px-4 text-center">
        <h1 className="font-semibold text-2xl">{t("notFound")}</h1>
        <p className="text-muted-foreground text-sm">{t("notFoundDescription")}</p>
        <Button variant="outline" asChild>
          <Link to={gp("/counter-groups")}>{t("backToGroups")}</Link>
        </Button>
      </div>
    );
  }

  if (!counter) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-background px-4 text-center">
        <h1 className="font-semibold text-2xl">{t("focus.notFound")}</h1>
        <Button variant="outline" asChild>
          <Link to={gp(`/counter-groups/${groupId}`)}>{t("backToGroup")}</Link>
        </Button>
      </div>
    );
  }

  const bg = counter.color ?? "hsl(var(--background))";
  const fg = getContrastingTextColor(counter.color) ?? "hsl(var(--foreground))";
  const isLight = fg === "#0F172A";
  const hasBounds = counter.min !== null && counter.max !== null;

  const stepButtonClass = isLight
    ? "bg-black/15 hover:bg-black/25 active:bg-black/35"
    : "bg-white/15 hover:bg-white/25 active:bg-white/35";

  const chromeButtonClass = isLight
    ? "hover:bg-black/10 focus-visible:bg-black/10"
    : "hover:bg-white/10 focus-visible:bg-white/10";

  let viewElement: React.ReactNode;
  if (counter.view_mode === "progress_bar" && hasBounds) {
    viewElement = (
      <CounterProgressBarView
        count={counter.count}
        min={counter.min!}
        max={counter.max!}
        step={counter.step}
        disabled={!canWrite}
        textColor={fg}
        onCommit={(value) => {
          stepper.cancel(counter.id);
          setCount.mutate({ counterId: counter.id, data: { count: value } });
        }}
        ariaLabel={counter.name}
        size="2xl"
      />
    );
  } else if (counter.view_mode === "segmented_clock" && hasBounds) {
    viewElement = (
      <CounterSegmentedClockView
        count={counter.count}
        min={counter.min!}
        max={counter.max!}
        step={counter.step}
        disabled={!canWrite}
        textColor={fg}
        onCommit={(value) => {
          stepper.cancel(counter.id);
          setCount.mutate({ counterId: counter.id, data: { count: value } });
        }}
        ariaLabel={counter.name}
        size="2xl"
      />
    );
  } else {
    viewElement = (
      <CounterNumberView
        count={counter.count}
        step={counter.step}
        disabled={!canWrite}
        textColor={fg}
        onCommit={(value) => {
          stepper.cancel(counter.id);
          setCount.mutate({ counterId: counter.id, data: { count: value } });
        }}
        ariaLabel={counter.name}
        size="2xl"
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col" style={{ background: bg, color: fg }}>
      <header className="flex items-center justify-between gap-2 px-3 pt-[max(env(safe-area-inset-top),0.75rem)] pb-2">
        <Button
          variant="ghost"
          size="icon"
          asChild
          aria-label={t("focus.exit")}
          className={cn("h-10 w-10", chromeButtonClass)}
          style={{ color: fg }}
        >
          <Link to={gp(`/counter-groups/${groupId}`)}>
            <X className="h-5 w-5" />
          </Link>
        </Button>
        <h1
          className="min-w-0 flex-1 truncate text-center font-semibold text-lg"
          title={counter.name}
        >
          {counter.name}
        </h1>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("more")}
              className={cn("h-10 w-10", chromeButtonClass)}
              style={{ color: fg }}
            >
              <MoreVertical className="h-5 w-5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={!canWrite}
              onSelect={() => {
                stepper.cancel(counter.id);
                resetOne.mutate(counter.id);
              }}
            >
              <RotateCcw className="h-4 w-4" />
              {t("reset")}
            </DropdownMenuItem>
            <DropdownMenuItem disabled={!canWrite} onSelect={() => setEditing(counter)}>
              <Pencil className="h-4 w-4" />
              {t("editCounter")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      {counters.length > 1 && (
        <div className="flex items-center justify-between gap-3 px-3 pb-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => goToCounter(currentIndex - 1)}
            aria-label={t("focus.previous")}
            className={cn("h-10 w-10", chromeButtonClass)}
            style={{ color: fg }}
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <span className="font-mono text-sm tabular-nums opacity-70">
            {t("focus.counterPosition", {
              current: currentIndex + 1,
              total: counters.length,
            })}
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => goToCounter(currentIndex + 1)}
            aria-label={t("focus.next")}
            className={cn("h-10 w-10", chromeButtonClass)}
            style={{ color: fg }}
          >
            <ChevronRight className="h-5 w-5" />
          </Button>
        </div>
      )}

      <div
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-6 py-4"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className="flex w-full max-w-sm items-center justify-center sm:max-w-md">
          {viewElement}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 px-3 pt-2 pb-[max(env(safe-area-inset-bottom),0.75rem)]">
        <Button
          type="button"
          variant="ghost"
          onClick={() => stepper.decrement(counter)}
          disabled={!canWrite}
          aria-label={t("decrement")}
          className={cn("h-24 rounded-2xl text-current shadow-sm sm:h-28", stepButtonClass)}
          style={{ color: fg }}
        >
          <Minus className="h-10 w-10" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => stepper.increment(counter)}
          disabled={!canWrite}
          aria-label={t("increment")}
          className={cn("h-24 rounded-2xl text-current shadow-sm sm:h-28", stepButtonClass)}
          style={{ color: fg }}
        >
          <Plus className="h-10 w-10" />
        </Button>
      </div>

      {canWrite && editing && (
        <CounterFormDialog
          open={!!editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          groupId={groupId}
          counter={editing}
        />
      )}
    </div>
  );
}
