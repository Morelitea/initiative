import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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

type ProjectFilterPresetDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { name: string; isDefault: boolean }) => void;
  isSubmitting?: boolean;
};

/**
 * Name the filters currently on screen and save them for the whole project.
 * Only rendered for someone who may curate presets — the server decides that
 * and says so in the preset list's `can_manage`.
 */
export const ProjectFilterPresetDialog = ({
  open,
  onOpenChange,
  onSubmit,
  isSubmitting,
}: ProjectFilterPresetDialogProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const [name, setName] = useState("");
  const [isDefault, setIsDefault] = useState(false);

  useEffect(() => {
    if (open) {
      setName("");
      setIsDefault(false);
    }
  }, [open]);

  const trimmed = name.trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            onSubmit({ name: trimmed, isDefault });
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("projects:filters.saveAsPreset")}</DialogTitle>
            <DialogDescription>{t("projects:filters.savePresetDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="preset-name">{t("projects:filters.presetName")}</Label>
              <Input
                id="preset-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("projects:filters.presetNamePlaceholder")}
                maxLength={100}
                autoFocus
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="preset-default"
                checked={isDefault}
                onCheckedChange={(checked) => setIsDefault(checked === true)}
              />
              <Label htmlFor="preset-default" className="cursor-pointer font-medium text-sm">
                {t("projects:filters.presetSetDefault")}
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={!trimmed || isSubmitting}>
              {isSubmitting ? t("common:submitting") : t("common:save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
