import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CounterGroupRead, ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { ShareControl } from "@/components/access/ShareControl";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreateCounterGroup } from "@/hooks/useCounters";
import { useInitiatives } from "@/hooks/useInitiatives";
import type { DialogProps } from "@/types/dialog";

type CreateCounterGroupDialogProps = DialogProps & {
  initiativeId?: number;
  defaultInitiativeId?: number;
  onSuccess?: (group: CounterGroupRead) => void;
};

export const CreateCounterGroupDialog = ({
  open,
  onOpenChange,
  initiativeId,
  defaultInitiativeId,
  onSuccess,
}: CreateCounterGroupDialogProps) => {
  const { t } = useTranslation(["counterGroups", "common"]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([
    { all_initiative_members: true, level: "read" },
  ]);

  const initiativesQuery = useInitiatives();
  const initiatives = initiativesQuery.data ?? [];

  const effectiveInitiativeId =
    initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null);

  const lockedInitiative = initiativeId
    ? (initiatives.find((i) => i.id === initiativeId) ?? null)
    : null;

  useEffect(() => {
    if (open) {
      if (defaultInitiativeId) {
        setSelectedInitiativeId(String(defaultInitiativeId));
      }
    } else {
      setName("");
      setDescription("");
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
      setGrants([{ all_initiative_members: true, level: "read" }]);
    }
  }, [open, defaultInitiativeId]);

  const createGroup = useCreateCounterGroup({
    onSuccess: (group) => {
      onOpenChange(false);
      onSuccess?.(group);
    },
  });

  const isCreating = createGroup.isPending;
  const canSubmit = !!name.trim() && !!effectiveInitiativeId && !isCreating;

  const handleSubmit = () => {
    const trimmedName = name.trim();
    if (!trimmedName || !effectiveInitiativeId) return;
    createGroup.mutate({
      name: trimmedName,
      description: description.trim() || undefined,
      initiative_id: effectiveInitiativeId,
      grants,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border bg-card shadow-2xl">
        <DialogHeader>
          <DialogTitle>{t("createGroup")}</DialogTitle>
          <DialogDescription>{t("noGroupsDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="create-counter-group-name">{t("name")}</Label>
            <Input
              id="create-counter-group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("namePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-counter-group-description">{t("description")}</Label>
            <Textarea
              id="create-counter-group-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("descriptionPlaceholder")}
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-counter-group-initiative">{t("initiative")}</Label>
            {initiativeId ? (
              <div className="rounded-md border px-3 py-2 text-sm">
                {lockedInitiative?.name ?? t("selectInitiative")}
              </div>
            ) : (
              <Select value={selectedInitiativeId} onValueChange={setSelectedInitiativeId}>
                <SelectTrigger id="create-counter-group-initiative">
                  <SelectValue placeholder={t("selectInitiative")} />
                </SelectTrigger>
                <SelectContent>
                  {initiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <Accordion type="single" collapsible defaultValue="advanced">
            <AccordionItem value="advanced" className="border-b-0">
              <AccordionTrigger>{t("common:createAccess.advancedOptions")}</AccordionTrigger>
              <AccordionContent>
                <ShareControl
                  initiativeId={effectiveInitiativeId}
                  grants={grants}
                  onChange={setGrants}
                />
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isCreating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("creating")}
              </>
            ) : (
              t("createGroup")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
