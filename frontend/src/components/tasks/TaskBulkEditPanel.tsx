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
  return (
    <div className="border-primary bg-primary/5 flex items-center justify-between rounded-md border p-4">
      <div className="text-sm font-medium">
        {selectedTasks.length} task{selectedTasks.length === 1 ? "" : "s"} selected
      </div>

      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onEditTags}>
          <Tags className="h-4 w-4" />
          Edit Tags
        </Button>
        <Button variant="outline" size="sm" onClick={onEdit}>
          <Pencil className="h-4 w-4" />
          Edit
        </Button>
        <Button variant="outline" size="sm" onClick={onArchive} disabled={isArchiving}>
          <Archive className="h-4 w-4" />
          {isArchiving ? "Archiving…" : "Archive"}
        </Button>
        <Button variant="destructive" size="sm" onClick={onDelete}>
          <Trash2 className="h-4 w-4" />
          Delete
        </Button>
      </div>
    </div>
  );
};
