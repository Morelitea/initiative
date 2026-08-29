/**
 * Create an initiative: name, description, colour, who may join, and which
 * optional tools it starts with.
 *
 * Lifted out of the old initiatives page so the guild home — now the only
 * initiative list — can offer the same form. The caller owns the open state
 * (a header button and the `?create=true` deep link both drive it) and is
 * responsible for the permission gate; creating is guild-admin only, which the
 * backend enforces regardless.
 */

import { Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeCreate, Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeJoinPolicy } from "@/api/generated/initiativeAPI.schemas";
import { AdvancedToolsSection } from "@/components/initiatives/AdvancedToolsToggles";
import { JoinPolicySection } from "@/components/initiatives/JoinPolicySection";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCreateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { TOGGLEABLE_TOOLS, toolViewPermission } from "@/lib/tools";

const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export interface CreateInitiativeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const CreateInitiativeDialog = ({ open, onOpenChange }: CreateInitiativeDialogProps) => {
  const { t } = useTranslation("initiatives");

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(DEFAULT_INITIATIVE_COLOR);
  const [joinPolicy, setJoinPolicy] = useState<InitiativeJoinPolicy>(InitiativeJoinPolicy.private);
  // Master-switch state per toggleable tool.
  const [toolSwitches, setToolSwitches] = useState<Partial<Record<Tool, boolean>>>({});

  const createInitiative = useCreateInitiative();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("createDialog.nameRequired"));
      return;
    }
    createInitiative.mutate(
      {
        name: trimmedName,
        description: description.trim() || undefined,
        color,
        join_policy: joinPolicy,
        // One `{plural}_enabled` field per toggleable tool, derived.
        ...(Object.fromEntries(
          TOGGLEABLE_TOOLS.map((tool) => [toolViewPermission(tool), toolSwitches[tool] ?? false])
        ) as Partial<InitiativeCreate>),
      },
      {
        onSuccess: () => {
          onOpenChange(false);
          setName("");
          setDescription("");
          setColor(DEFAULT_INITIATIVE_COLOR);
          setJoinPolicy(InitiativeJoinPolicy.private);
          setToolSwitches({});
        },
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-screen overflow-y-auto bg-card">
        <DialogHeader>
          <DialogTitle>{t("createDialog.title")}</DialogTitle>
          <DialogDescription>{t("createDialog.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="new-initiative-name">{t("createDialog.nameLabel")}</Label>
            <Input
              id="new-initiative-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("createDialog.namePlaceholder")}
              required
              disabled={createInitiative.isPending}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-initiative-description">{t("createDialog.descriptionLabel")}</Label>
            <Textarea
              id="new-initiative-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("createDialog.descriptionPlaceholder")}
              rows={3}
              disabled={createInitiative.isPending}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-initiative-color">{t("createDialog.colorLabel")}</Label>
            <ColorPickerPopover
              id="new-initiative-color"
              value={color}
              onChange={setColor}
              triggerLabel="Adjust"
              disabled={createInitiative.isPending}
            />
            <p className="text-muted-foreground text-xs">{t("createDialog.colorHint")}</p>
          </div>
          <div className="space-y-2">
            <Label>{t("settings.joinPolicy.title")}</Label>
            <JoinPolicySection
              layout="plain"
              idPrefix="create"
              value={joinPolicy}
              onChange={setJoinPolicy}
              canManage={!createInitiative.isPending}
              isSaving={createInitiative.isPending}
            />
          </div>
          <Accordion type="single" collapsible>
            <AccordionItem value="advanced-tools">
              <AccordionTrigger>{t("advancedTools")}</AccordionTrigger>
              <AccordionContent>
                <p className="mb-3 text-muted-foreground text-sm">
                  {t("advancedToolsDescription")}
                </p>
                <AdvancedToolsSection
                  layout="plain"
                  canManage={!createInitiative.isPending}
                  isSaving={createInitiative.isPending}
                  values={toolSwitches}
                  onToggle={(tool, value) =>
                    setToolSwitches((prev) => ({ ...prev, [tool]: value }))
                  }
                  idPrefix="create"
                />
              </AccordionContent>
            </AccordionItem>
          </Accordion>
          <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button type="submit" disabled={createInitiative.isPending}>
              {createInitiative.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("createDialog.creating")}
                </>
              ) : (
                t("createDialog.submit")
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
