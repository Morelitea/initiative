import { ChevronDown, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ActHeldButtonProps {
  itemId: number;
  /**
   * `reposition: false` clears the hold and keeps the original queue
   * position (the row will act at its natural slot when the rotation
   * reaches it). `reposition: true` lifts the row above the current turn
   * and makes it the current turn — PF2e Delay semantics.
   */
  onAct: (itemId: number, reposition: boolean) => void;
}

/**
 * Released-from-hold action button, shared by On Deck and List views.
 *
 * Renders the Zap + "Act" trigger with a dropdown offering the two release
 * semantics. The trigger and menu items both `stopPropagation` so clicks
 * here don't fall through to the surrounding row (which would open the
 * edit dialog).
 */
export const ActHeldButton = ({ itemId, onAct }: ActHeldButtonProps) => {
  const { t } = useTranslation("queues");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild onClick={(event) => event.stopPropagation()}>
        <Button type="button" size="sm" aria-label={t("actNow")}>
          <Zap className="h-4 w-4" />
          {t("actNow")}
          <ChevronDown className="h-3 w-3" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(event) => event.stopPropagation()}>
        <DropdownMenuItem onSelect={() => onAct(itemId, false)}>
          <div className="flex flex-col">
            <span className="font-medium">{t("actInPlace")}</span>
            <span className="text-muted-foreground text-xs">{t("actInPlaceDescription")}</span>
          </div>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAct(itemId, true)}>
          <div className="flex flex-col">
            <span className="font-medium">{t("actReposition")}</span>
            <span className="text-muted-foreground text-xs">{t("actRepositionDescription")}</span>
          </div>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
