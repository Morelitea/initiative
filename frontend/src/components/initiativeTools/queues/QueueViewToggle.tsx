import { ArrowDownFromLine, List } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type QueueView = "list" | "on-deck";

interface QueueViewToggleProps {
  view: QueueView;
  onChange: (view: QueueView) => void;
}

export const QueueViewToggle = ({ view, onChange }: QueueViewToggleProps) => {
  const { t } = useTranslation("queues");

  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={view}
      variant="outline"
      onValueChange={(next) => {
        // Radix emits "" when the user clicks the active item; ignore that so
        // a view is always selected.
        if (next === "list" || next === "on-deck") onChange(next);
      }}
      aria-label={t("viewLabel")}
    >
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <ToggleGroupItem
            value="on-deck"
            aria-label={t("viewOnDeck")}
            className={cn(view === "on-deck" && "bg-muted")}
          >
            <ArrowDownFromLine className="h-4 w-4" />
          </ToggleGroupItem>
        </TooltipTrigger>
        <TooltipContent>{t("viewOnDeck")}</TooltipContent>
      </Tooltip>
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <ToggleGroupItem
            value="list"
            aria-label={t("viewList")}
            className={cn(view === "list" && "bg-muted")}
          >
            <List className="h-4 w-4" />
          </ToggleGroupItem>
        </TooltipTrigger>
        <TooltipContent>{t("viewList")}</TooltipContent>
      </Tooltip>
    </ToggleGroup>
  );
};
