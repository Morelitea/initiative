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

type ProjectViewDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { name: string; isDefault: boolean }) => void;
  isSubmitting?: boolean;
};

/**
 * Name the layout and filters currently on screen and save them as a view for
 * the whole project. Only rendered for someone who may configure the project's
 * views — the server decides that and says so in the set's `can_configure`.
 */
export const ProjectViewDialog = ({
  open,
  onOpenChange,
  onSubmit,
  isSubmitting,
}: ProjectViewDialogProps) => {
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
            <DialogTitle>{t("projects:views.saveAs")}</DialogTitle>
            <DialogDescription>{t("projects:views.saveAsDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="view-name">{t("projects:views.name")}</Label>
              <Input
                id="view-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("projects:views.namePlaceholder")}
                maxLength={100}
                autoFocus
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="view-default"
                checked={isDefault}
                onCheckedChange={(checked) => setIsDefault(checked === true)}
              />
              <Label htmlFor="view-default" className="cursor-pointer font-medium text-sm">
                {t("projects:views.setDefault")}
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
