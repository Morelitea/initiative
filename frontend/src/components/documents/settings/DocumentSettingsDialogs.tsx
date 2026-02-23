import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

interface DocumentSettingsDialogsProps {
  documentTitle: string;
  // Duplicate dialog
  duplicateDialogOpen: boolean;
  onDuplicateDialogOpenChange: (open: boolean) => void;
  duplicateTitle: string;
  onDuplicateTitleChange: (title: string) => void;
  onDuplicate: (title: string) => void;
  isDuplicating: boolean;
  // Copy dialog
  copyDialogOpen: boolean;
  onCopyDialogOpenChange: (open: boolean) => void;
  copyTitle: string;
  onCopyTitleChange: (title: string) => void;
  copyInitiativeId: string;
  onCopyInitiativeIdChange: (id: string) => void;
  onCopy: (initiativeId: string, title: string) => void;
  isCopying: boolean;
  copyableInitiatives: InitiativeRead[];
  isLoadingInitiatives: boolean;
  // Delete dialog
  deleteDialogOpen: boolean;
  onDeleteDialogOpenChange: (open: boolean) => void;
  onDelete: () => void;
  isDeleting: boolean;
}

export const DocumentSettingsDialogs = ({
  documentTitle,
  // Duplicate dialog
  duplicateDialogOpen,
  onDuplicateDialogOpenChange,
  duplicateTitle,
  onDuplicateTitleChange,
  onDuplicate,
  isDuplicating,
  // Copy dialog
  copyDialogOpen,
  onCopyDialogOpenChange,
  copyTitle,
  onCopyTitleChange,
  copyInitiativeId,
  onCopyInitiativeIdChange,
  onCopy,
  isCopying,
  copyableInitiatives,
  isLoadingInitiatives,
  // Delete dialog
  deleteDialogOpen,
  onDeleteDialogOpenChange,
  onDelete,
  isDeleting,
}: DocumentSettingsDialogsProps) => {
  const { t } = useTranslation(["documents", "common"]);

  return (
    <>
      <Dialog open={duplicateDialogOpen} onOpenChange={onDuplicateDialogOpenChange}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("settings.duplicateDialogTitle")}</DialogTitle>
            <DialogDescription>{t("settings.duplicateDialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="duplicate-document-title">{t("settings.duplicateTitleLabel")}</Label>
            <Input
              id="duplicate-document-title"
              value={duplicateTitle}
              onChange={(event) => onDuplicateTitleChange(event.target.value)}
              placeholder={t("settings.duplicateTitlePlaceholder", { title: documentTitle })}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onDuplicateDialogOpenChange(false)}
            >
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = duplicateTitle.trim();
                if (!trimmedTitle) return;
                onDuplicate(trimmedTitle);
              }}
              disabled={isDuplicating || !duplicateTitle.trim()}
            >
              {isDuplicating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.duplicating")}
                </>
              ) : (
                t("bulk.duplicate")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={copyDialogOpen} onOpenChange={onCopyDialogOpenChange}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("settings.copyDialogTitle")}</DialogTitle>
            <DialogDescription>{t("settings.copyDialogDescription")}</DialogDescription>
          </DialogHeader>
          {isLoadingInitiatives ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("settings.loadingInitiatives")}
            </div>
          ) : copyableInitiatives.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("settings.managerAccessRequired")}</p>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="copy-document-initiative">{t("settings.targetInitiative")}</Label>
                <Select
                  value={copyInitiativeId || undefined}
                  onValueChange={(value) => onCopyInitiativeIdChange(value)}
                >
                  <SelectTrigger id="copy-document-initiative">
                    <SelectValue placeholder={t("settings.selectInitiative")} />
                  </SelectTrigger>
                  <SelectContent>
                    {copyableInitiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="copy-document-title">{t("settings.duplicateTitleLabel")}</Label>
                <Input
                  id="copy-document-title"
                  value={copyTitle}
                  onChange={(event) => onCopyTitleChange(event.target.value)}
                  placeholder={documentTitle}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onCopyDialogOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = copyTitle.trim();
                if (!trimmedTitle || !copyInitiativeId) return;
                onCopy(copyInitiativeId, trimmedTitle);
              }}
              disabled={
                isCopying ||
                copyableInitiatives.length === 0 ||
                !copyInitiativeId ||
                !copyTitle.trim()
              }
            >
              {isCopying ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.copying")}
                </>
              ) : (
                t("settings.copyDocument")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={onDeleteDialogOpenChange}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("settings.deleteDialogTitle")}</DialogTitle>
            <DialogDescription>{t("settings.deleteDialogDescription")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onDeleteDialogOpenChange(false)}
            >
              {t("common:cancel")}
            </Button>
            <Button type="button" variant="destructive" onClick={onDelete} disabled={isDeleting}>
              {isDeleting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.deleting")}
                </>
              ) : (
                t("common:delete")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
