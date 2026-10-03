import { ChevronLeft, ChevronRight, Hand, Loader2, Pause, Play, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { QueueRead } from "@/api/generated/initiativeAPI.schemas";
import { ToolChestSegment } from "@/components/tools/ToolChest";
import { Button } from "@/components/ui/button";

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

/** The queue's round and the buttons that run it, as segments of its tool
 *  chest. */
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
  // Previous / Next / Hold need a current turn to operate on; without one
  // (e.g. when every visible item has been held) clicking would either no-op
  // on the server or surprise the user.
  const noTurn = !queue.is_active || !queue.current_item || isLoading;

  return (
    <>
      <ToolChestSegment label={t("round")}>
        {queue.is_active ? (
          <span className="font-mono tabular-nums">{queue.current_round}</span>
        ) : (
          <span className="text-muted-foreground">{t("inactive")}</span>
        )}
      </ToolChestSegment>
      {queue.can.edit ? (
        <ToolChestSegment>
          <Button
            variant={queue.is_active ? "destructive" : "default"}
            size="sm"
            onClick={queue.is_active ? onStop : onStart}
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : queue.is_active ? (
              <Pause className="h-4 w-4" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            {queue.is_active ? t("stop") : t("start")}
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={onPrevious}
            disabled={noTurn}
            aria-label={t("previous")}
            title={t("previous")}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={onNext}
            disabled={noTurn}
            aria-label={t("next")}
            title={t("next")}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          {/* Hold the current turn — they leave the rotation until released
              or their natural slot comes back around. */}
          <Button variant="outline" size="sm" onClick={onHold} disabled={noTurn}>
            <Hand className="h-4 w-4" />
            {t("hold")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onReset} disabled={isLoading}>
            <RotateCcw className="h-4 w-4" />
            {t("reset")}
          </Button>
        </ToolChestSegment>
      ) : null}
    </>
  );
};
