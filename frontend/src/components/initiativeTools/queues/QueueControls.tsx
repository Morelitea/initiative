import { ChevronLeft, ChevronRight, Hand, Loader2, Pause, Play, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { QueueRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface QueueControlsProps {
  queue: QueueRead;
  onStart: () => void;
  onStop: () => void;
  onNext: () => void;
  onPrevious: () => void;
  onReset: () => void;
  onHold: () => void;
  isLoading?: boolean;
}

export const QueueControls = ({
  queue,
  onStart,
  onStop,
  onNext,
  onPrevious,
  onReset,
  onHold,
  isLoading = false,
}: QueueControlsProps) => {
  const { t } = useTranslation("queues");
  const canControl = queue.my_permission_level === "owner" || queue.my_permission_level === "write";

  if (!canControl) {
    return (
      <div className="flex items-center gap-3 rounded-lg border px-4 py-3">
        <Badge variant={queue.is_active ? "default" : "secondary"}>
          {queue.is_active ? t("active") : t("inactive")}
        </Badge>
        {queue.is_active && (
          <span className="font-medium text-muted-foreground text-sm">
            {t("roundN", { count: queue.current_round })}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border px-4 py-3">
      {/* Start / Stop toggle */}
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <Button
            variant={queue.is_active ? "destructive" : "default"}
            size="sm"
            onClick={queue.is_active ? onStop : onStart}
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : queue.is_active ? (
              <Pause className="mr-1 h-4 w-4" />
            ) : (
              <Play className="mr-1 h-4 w-4" />
            )}
            {queue.is_active ? t("stop") : t("start")}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{queue.is_active ? t("stop") : t("start")}</p>
        </TooltipContent>
      </Tooltip>

      {/* Previous / Next / Hold need a current turn to operate on; without
          one (e.g. when every visible item has been held) clicking would
          either no-op on the server or surprise the user. */}
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            onClick={onPrevious}
            disabled={!queue.is_active || !queue.current_item || isLoading}
            aria-label={t("previous")}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{t("previous")}</p>
        </TooltipContent>
      </Tooltip>

      {/* Next */}
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            onClick={onNext}
            disabled={!queue.is_active || !queue.current_item || isLoading}
            aria-label={t("next")}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{t("next")}</p>
        </TooltipContent>
      </Tooltip>

      {/* Hold the current turn — they leave the rotation until released or
          their natural slot comes back around. */}
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            onClick={onHold}
            disabled={!queue.is_active || !queue.current_item || isLoading}
          >
            <Hand className="mr-1 h-4 w-4" />
            {t("hold")}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{t("hold")}</p>
        </TooltipContent>
      </Tooltip>

      {/* Round counter */}
      {queue.is_active && (
        <Badge variant="outline" className="ml-2 font-mono text-sm">
          {t("roundN", { count: queue.current_round })}
        </Badge>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Reset */}
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" onClick={onReset} disabled={isLoading}>
            <RotateCcw className="mr-1 h-4 w-4" />
            {t("reset")}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{t("reset")}</p>
        </TooltipContent>
      </Tooltip>
    </div>
  );
};
