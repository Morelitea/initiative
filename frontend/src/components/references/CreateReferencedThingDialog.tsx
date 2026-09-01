import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { isToolEnabled, TOOL_ICONS, TOOLS, toolCreateTarget, toolNavLabelKey } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface CreateReferencedThingDialogProps {
  /** The name that was typed and found nothing. */
  name: string;
  initiativeId: number;
  onClose: () => void;
}

/**
 * Making the thing `[[ ]]` could not find.
 *
 * Which kind is the writer's choice, so this asks — but it only offers tools
 * this initiative actually has and this writer may add to, because a create
 * path that puts back a switched-off tool would be a way around the switch.
 */
export function CreateReferencedThingDialog({
  name,
  initiativeId,
  onClose,
}: CreateReferencedThingDialogProps) {
  const { t } = useTranslation(["comments", "common", "nav"]);
  const guildPath = useGuildPath();
  const navigate = useNavigate();
  const { data: initiative } = useInitiative(initiativeId);
  const { permissionsFor } = useInitiativeAccess();
  const [chosen, setChosen] = useState<Tool | null>(null);

  const permissions = initiative ? permissionsFor(initiative) : null;
  const offered = TOOLS.filter(
    (tool) => initiative && isToolEnabled(tool, initiative) && Boolean(permissions?.[tool]?.create)
  );

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("createNamed", { name })}</DialogTitle>
          <DialogDescription>{t("createKindPrompt")}</DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2">
          {offered.map((tool) => {
            const Icon = TOOL_ICONS[tool];
            return (
              <button
                key={tool}
                type="button"
                onClick={() => setChosen(tool)}
                className={cn(
                  "flex items-center gap-2 rounded-md border-2 px-3 py-2 text-left text-sm",
                  chosen === tool
                    ? "border-primary bg-primary/5"
                    : "border-transparent bg-muted hover:border-muted-foreground/30"
                )}
              >
                <Icon className="size-4 shrink-0" />
                {t(`nav:${toolNavLabelKey(tool)}` as never)}
              </button>
            );
          })}
        </div>
        {offered.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("createNothingAllowed")}</p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common:cancel")}
          </Button>
          <Button
            disabled={chosen === null}
            onClick={() => {
              if (chosen === null) return;
              // The tool's own create surface owns making one — this only says
              // which, and carries the name across so it arrives filled in.
              // The tool's own create surface owns making one. The typed name
              // does not travel with it yet — every tool route would have to
              // accept it — so the dialog opens empty and the writer names it
              // there.
              const target = toolCreateTarget(chosen, initiativeId);
              void navigate({ to: guildPath(target.to), search: target.search });
            }}
          >
            {t("common:create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
