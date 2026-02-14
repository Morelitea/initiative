import { useTranslation } from "react-i18next";
import { Archive, Pencil, Tags, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Task } from "@/types/api";

type TaskBulkEditPanelProps = {
  selectedTasks: Task[];
  onEdit: () => void;
  onEditTags: () => void;
  onArchive: () => void;
  onDelete: () => void;
  isArchiving?: boolean;
};

export const TaskBulkEditPanel = ({
  selectedTasks,
  onEdit,
  onEditTags,
  onArchive,
  onDelete,
  isArchiving,
}: TaskBulkEditPanelProps) => {
  const { t } = useTranslation("tasks");
  return (
    <div className="border-primary bg-primary/5 flex items-center justify-between rounded-md border p-4">
      <div className="text-sm font-medium">
        {t("bulkEdit.selected", { count: selectedTasks.length })}
      </div>

      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onEditTags}>
          <Tags className="h-4 w-4" />
          {t("bulkEdit.editTags")}
        </Button>
        <Button variant="outline" size="sm" onClick={onEdit}>
          <Pencil className="h-4 w-4" />
          {t("common:edit")}
        </Button>
        <Button variant="outline" size="sm" onClick={onArchive} disabled={isArchiving}>
          <Archive className="h-4 w-4" />
          {isArchiving ? t("edit.archiving") : t("edit.archive")}
        </Button>
        <Button variant="destructive" size="sm" onClick={onDelete}>
          <Trash2 className="h-4 w-4" />
          {t("common:delete")}
        </Button>
      </div>
    </div>
  );
};
