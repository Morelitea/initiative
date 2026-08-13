import { Link } from "@tanstack/react-router";
import { ChevronDown, Pin, PinOff, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { FOCUS_HORIZON_ANY, FOCUS_PRIORITIES, type useFocusSummary } from "@/hooks/useFocusSummary";
import { guildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

type FocusSummaryData = ReturnType<typeof useFocusSummary>;

export type FocusSummaryProps = {
  focus: FocusSummaryData;
  activeGuildId: number | null;
  /** Reused from the page's table so status resolution has one implementation. */
  changeTaskStatus: (task: TaskListRead, category: TaskStatusCategory) => Promise<void>;
  isUpdatingTaskStatus: boolean;
};

const taskHref = (task: TaskListRead, activeGuildId: number | null) => {
  const guildId = task.guild_id ?? activeGuildId;
  const path = `/tasks/${task.id}`;
  return guildId ? guildPath(guildId, path) : path;
};

type FocusRowProps = {
  task: TaskListRead;
  activeGuildId: number | null;
  isPinned: boolean;
  onTogglePin: () => void;
  onToggleDone: () => void;
  disabled: boolean;
  done?: boolean;
};

const FocusRow = ({
  task,
  activeGuildId,
  isPinned,
  onTogglePin,
  onToggleDone,
  disabled,
  done = false,
}: FocusRowProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const context = [task.project_name, task.guild_name].filter(Boolean).join(" · ");

  return (
    <div className="group flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-muted/50">
      <Checkbox
        checked={done}
        disabled={disabled}
        onCheckedChange={() => onToggleDone()}
        aria-label={done ? t("checkbox.markInProgress") : t("checkbox.markDone")}
      />
      <div className="min-w-0 flex-1">
        <Link
          to={taskHref(task, activeGuildId)}
          className={cn(
            "block truncate font-medium text-sm hover:underline",
            done && "text-muted-foreground line-through"
          )}
        >
          {task.title}
        </Link>
        {context ? <p className="truncate text-muted-foreground text-xs">{context}</p> : null}
      </div>
      {!done && task.due_date ? (
        <div className="hidden shrink-0 text-xs sm:block">
          <DateCell date={task.due_date} isPastVariant="destructive" />
        </div>
      ) : null}
      <Button
        variant="ghost"
        size="sm"
        className={cn(
          "h-7 w-7 shrink-0 p-0",
          !isPinned && "opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
        )}
        onClick={onTogglePin}
        aria-label={isPinned ? t("focus.unpin") : t("focus.pin")}
        title={isPinned ? t("focus.unpin") : t("focus.pin")}
      >
        {isPinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
};

const FocusSettings = ({ focus }: { focus: FocusSummaryData }) => {
  const { t } = useTranslation(["tasks", "common"]);
  const { prefs, setHorizon } = focus;

  /** What a slider stop means, in words: the same value the leg is built from. */
  const horizonLabel = (days: number) => {
    if (days >= FOCUS_HORIZON_ANY) return t("focus.horizon.any");
    if (days === 0) return t("focus.horizon.today");
    return t("focus.horizon.days", { count: days });
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" aria-label={t("focus.settings")}>
          <Settings2 className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 space-y-4 sm:w-80">
        <div className="space-y-1">
          <Label className="text-xs">{t("focus.horizonsLabel")}</Label>
          <p className="text-muted-foreground text-xs">{t("focus.horizonsHint")}</p>
        </div>

        <div className="space-y-4">
          {FOCUS_PRIORITIES.map((priority) => {
            const days = prefs.horizons[priority];
            const label = t(`priority.${priority}`);
            return (
              <div key={priority} className="space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <Label className="text-xs capitalize">{label}</Label>
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {horizonLabel(days)}
                  </span>
                </div>
                <Slider
                  value={[days]}
                  min={0}
                  max={FOCUS_HORIZON_ANY}
                  step={1}
                  thumbLabel={label}
                  onValueChange={([next]) => setHorizon(priority, next)}
                  // The whole track is draggable, so the padding is what makes
                  // it a finger-sized target rather than a 4px line.
                  className="py-1.5"
                />
              </div>
            );
          })}
        </div>

        <p className="text-muted-foreground text-xs">{t("focus.settingsHint")}</p>
      </PopoverContent>
    </Popover>
  );
};

/**
 * A short, capped list of what needs doing now, above the full task table.
 *
 * Deliberately not a second view of the table below it: it holds only what the
 * rules match plus what the user pinned, and it keeps today's completions
 * visible rather than dropping them the moment they're checked, so finishing
 * work reads as progress instead of disappearance.
 */
export const FocusSummary = ({
  focus,
  activeGuildId,
  changeTaskStatus,
  isUpdatingTaskStatus,
}: FocusSummaryProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const { pinned, upcoming, completedToday, truncated, doneCount, totalCount, prefs } = focus;

  const progress = totalCount > 0 ? (doneCount / totalCount) * 100 : 0;
  const open = prefs.open;

  const renderRow = (task: TaskListRead, done: boolean) => (
    <FocusRow
      key={`${task.guild_id ?? "none"}:${task.id}`}
      task={task}
      activeGuildId={activeGuildId}
      isPinned={focus.isPinned(task)}
      onTogglePin={() => focus.togglePin(task)}
      onToggleDone={() => void changeTaskStatus(task, done ? "in_progress" : "done")}
      disabled={isUpdatingTaskStatus}
      done={done}
    />
  );

  return (
    // The app shell supplies a tooltip context, but the section carries its own
    // so the date cells inside it work wherever it is mounted.
    <TooltipProvider delayDuration={300}>
      <Card>
        <Collapsible open={open} onOpenChange={(next) => focus.setPreference("open", next)}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="-ml-2 h-8 gap-2 px-2">
                  <ChevronDown
                    className={cn("h-4 w-4 transition-transform", !open && "-rotate-90")}
                  />
                  <span className="font-semibold text-base">{t("focus.title")}</span>
                </Button>
              </CollapsibleTrigger>
              {totalCount > 0 ? (
                <Badge variant="secondary" className="shrink-0">
                  {t("focus.progress", { done: doneCount, total: totalCount })}
                </Badge>
              ) : null}
            </div>
            <FocusSettings focus={focus} />
          </CardHeader>

          <CollapsibleContent>
            <CardContent className="pt-0 pb-4">
              {totalCount > 0 ? <Progress value={progress} className="mb-3 h-1" /> : null}

              {focus.hasError ? (
                <p className="py-4 text-center text-destructive text-sm">{t("focus.loadError")}</p>
              ) : focus.isEmpty ? (
                <p className="py-4 text-center text-muted-foreground text-sm">{t("focus.empty")}</p>
              ) : (
                <div className="space-y-0.5">
                  {pinned.map((task) => renderRow(task, false))}
                  {upcoming.map((task) => renderRow(task, false))}

                  {truncated ? (
                    <p className="px-2 pt-1 text-muted-foreground text-xs">
                      {t("focus.truncated", { shown: upcoming.length })}
                    </p>
                  ) : null}

                  {completedToday.length > 0 ? (
                    <>
                      <Separator className="my-2" />
                      {completedToday.map((task) => renderRow(task, true))}
                    </>
                  ) : null}
                </div>
              )}
            </CardContent>
          </CollapsibleContent>
        </Collapsible>
      </Card>
    </TooltipProvider>
  );
};
