import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { useUsers } from "@/hooks/useUsers";
import { getUserDisplayName } from "@/lib/userDisplay";
import type { TrashItemEntityType } from "@/api/generated/initiativeAPI.schemas";

export interface ReassignOwnerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: TrashItemEntityType;
  validOwnerIds: number[];
  onConfirm: (newOwnerId: number) => void;
  isPending?: boolean;
}

export const ReassignOwnerDialog = ({
  open,
  onOpenChange,
  entityType,
  validOwnerIds,
  onConfirm,
  isPending = false,
}: ReassignOwnerDialogProps) => {
  const { t } = useTranslation("trash");
  const { data: guildMembers } = useUsers();
  const [selected, setSelected] = useState<string>("");

  // Reset the picker every time the dialog reopens.
  useEffect(() => {
    if (open) {
      setSelected("");
    }
  }, [open]);

  const options = useMemo(() => {
    const validSet = new Set(validOwnerIds);
    return (guildMembers ?? [])
      .filter((m) => validSet.has(m.id))
      .map((m) => ({
        value: String(m.id),
        label: getUserDisplayName(m, `User #${m.id}`),
      }));
  }, [guildMembers, validOwnerIds]);

  const entityLabel = t(`entityType.${entityType}` as const);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("reassignDialog.title")}</DialogTitle>
          <DialogDescription>
            {t("reassignDialog.description", { type: entityLabel.toLowerCase() })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="reassign-owner">{t("reassignDialog.ownerLabel")}</Label>
          <SearchableCombobox
            items={options}
            value={selected}
            onValueChange={setSelected}
            aria-label={t("reassignDialog.ownerLabel")}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            {t("common:cancel", { defaultValue: "Cancel" })}
          </Button>
          <Button
            onClick={() => {
              const id = Number(selected);
              if (!Number.isFinite(id) || id <= 0) return;
              onConfirm(id);
            }}
            disabled={!selected || isPending}
          >
            {t("reassignDialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
