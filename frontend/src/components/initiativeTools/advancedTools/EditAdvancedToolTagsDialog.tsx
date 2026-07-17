import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AdvancedToolRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagPicker } from "@/components/tags";
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
import { useSetAdvancedToolTags } from "@/hooks/useToolTags";
import type { DialogProps } from "@/types/dialog";

type EditAdvancedToolTagsDialogProps = DialogProps & {
  tool: AdvancedToolRead;
};

/**
 * Advanced tools are authored in the external service and have no in-app
 * settings page, so tags are managed from this small dialog opened off the
 * tool's card. The picker holds the full selection and PUTs the complete tag
 * id list on every change.
 */
export const EditAdvancedToolTagsDialog = ({
  open,
  onOpenChange,
  tool,
}: EditAdvancedToolTagsDialogProps) => {
  const { t } = useTranslation(["advancedTools", "common"]);
  const [selectedTags, setSelectedTags] = useState<TagSummary[]>(tool.tags);

  useEffect(() => {
    if (open) setSelectedTags(tool.tags);
  }, [open, tool.tags]);

  const setTags = useSetAdvancedToolTags();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("editTagsTitle")}</DialogTitle>
          <DialogDescription>{t("editTagsDescription", { name: tool.name })}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>{t("tags")}</Label>
          <TagPicker
            selectedTags={selectedTags}
            onChange={(newTags) => {
              setSelectedTags(newTags);
              setTags.mutate({
                advancedToolId: tool.id,
                tagIds: newTags.map((tag) => tag.id),
              });
            }}
          />
        </div>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {t("common:done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
