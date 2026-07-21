import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  RestoreOwnerCandidate,
  TrashItemEntityType,
} from "@/api/generated/initiativeAPI.schemas";
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
import { getUserDisplayName } from "@/lib/userDisplay";

export interface ReassignOwnerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: TrashItemEntityType;
  // Eligible new owners (id + name), returned by the reassign-eligibility
  // response — so the picker needn't fetch the whole guild roster.
  validOwners: RestoreOwnerCandidate[];
  onConfirm: (newOwnerId: number) => void;
  isPending?: boolean;
}

export const ReassignOwnerDialog = ({
  open,
  onOpenChange,
  entityType,
  validOwners,
  onConfirm,
  isPending = false,
}: ReassignOwnerDialogProps) => {
  const { t } = useTranslation("trash");
  const [selected, setSelected] = useState<string>("");

  // Reset the picker every time the dialog reopens.
  useEffect(() => {
    if (open) {
      setSelected("");
    }
  }, [open]);

  const options = useMemo(
    () =>
      validOwners.map((owner) => ({
        value: String(owner.id),
        label: getUserDisplayName(owner, `User #${owner.id}`),
      })),
    [validOwners]
  );

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
