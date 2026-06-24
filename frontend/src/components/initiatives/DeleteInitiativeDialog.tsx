import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface DeleteInitiativeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initiativeName: string;
  isDeleting: boolean;
  onConfirm: () => void;
}

/**
 * The single delete-initiative confirmation flow: a type-the-name-to-confirm
 * guard before the whole tree (projects, docs, queues, events) is soft-deleted
 * to trash. Shared by the per-initiative settings page and the guild settings
 * Initiatives table so there is exactly one delete workflow to maintain. The
 * caller owns the mutation (via onConfirm/isDeleting); this only gates it.
 */
export const DeleteInitiativeDialog = ({
  open,
  onOpenChange,
  initiativeName,
  isDeleting,
  onConfirm,
}: DeleteInitiativeDialogProps) => {
  const { t } = useTranslation(["initiatives", "common"]);
  const [confirmText, setConfirmText] = useState("");
  const canConfirm = confirmText === initiativeName;

  // Reset the typed confirmation whenever the dialog (re)opens.
  useEffect(() => {
    if (open) setConfirmText("");
  }, [open]);

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setConfirmText("");
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("settings.deleteConfirmTitle")}</AlertDialogTitle>
          <AlertDialogDescription>
            <Trans
              i18nKey="settings.deleteConfirmDescription"
              ns="initiatives"
              values={{ name: initiativeName }}
              components={{ bold: <strong /> }}
            />
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2 py-2">
          <Label htmlFor="delete-initiative-confirm-input">
            <Trans
              i18nKey="settings.deleteConfirmLabel"
              ns="initiatives"
              values={{ name: initiativeName }}
              components={{ bold: <strong /> }}
            />
          </Label>
          <Input
            id="delete-initiative-confirm-input"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={initiativeName}
            autoComplete="off"
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>{t("common:cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={!canConfirm || isDeleting}
            className="bg-destructive text-white hover:bg-destructive/90"
          >
            {isDeleting ? t("settings.deletingInitiative") : t("common:delete")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
