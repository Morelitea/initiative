import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { AssigneeSelector } from "@/components/projects/AssigneeSelector";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import type {
  Task,
  ProjectTaskStatus,
  TaskPriority,
  TaskRecurrence,
  TaskRecurrenceStrategy,
} from "@/types/api";
import type { UserOption } from "@/components/projects/projectTasksConfig";

export type TaskBulkUpdate = {
  start_date: string | null;
  due_date: string | null;
  assignee_ids: number[];
  task_status_id: number;
  priority: TaskPriority;
  recurrence: TaskRecurrence | null;
  recurrence_strategy: TaskRecurrenceStrategy;
};

interface TaskBulkEditDialogProps {
  selectedTasks: Task[];
  taskStatuses: ProjectTaskStatus[];
  userOptions: UserOption[];
  isSubmitting: boolean;
  onApply: (changes: Partial<TaskBulkUpdate>) => void;
  onCancel: () => void;
}

export const TaskBulkEditDialog = ({
  selectedTasks,
  taskStatuses,
  userOptions,
  isSubmitting,
  onApply,
  onCancel,
}: TaskBulkEditDialogProps) => {
  const { t } = useTranslation("tasks");
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [statusId, setStatusId] = useState<string>("");
  const [priority, setPriority] = useState<string>("");
  const [recurrence, setRecurrence] = useState<TaskRecurrence | null>(null);
  const [recurrenceStrategy, setRecurrenceStrategy] = useState<TaskRecurrenceStrategy>("fixed");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const changes: Partial<TaskBulkUpdate> = {};

    if (startDate) {
      changes.start_date = new Date(startDate).toISOString();
    }

    if (dueDate) {
      changes.due_date = new Date(dueDate).toISOString();
    }

    if (assigneeIds.length > 0) {
      changes.assignee_ids = assigneeIds;
    }

    if (statusId) {
      changes.task_status_id = Number(statusId);
    }

    if (priority) {
      changes.priority = priority as TaskPriority;
    }

    if (recurrence) {
      changes.recurrence = recurrence;
      changes.recurrence_strategy = recurrenceStrategy;
    }

    if (Object.keys(changes).length > 0) {
      onApply(changes);
    }
  };

  const hasChanges =
    startDate || dueDate || assigneeIds.length > 0 || statusId || priority || recurrence;

  return (
    <DialogContent className="bg-card max-h-screen overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{t("bulkEdit.title")}</DialogTitle>
        <DialogDescription>
          {t("bulkEdit.description", { count: selectedTasks.length })}
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={handleSubmit}>
        <Accordion type="single" collapsible className="w-full">
          <AccordionItem value="dates">
            <AccordionTrigger>{t("bulkEdit.datesSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label htmlFor="bulk-start-date">{t("bulkEdit.startDateLabel")}</Label>
                <DateTimePicker
                  value={startDate}
                  onChange={setStartDate}
                  placeholder={t("bulkEdit.startDatePlaceholder")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bulk-due-date">{t("bulkEdit.dueDateLabel")}</Label>
                <DateTimePicker
                  value={dueDate}
                  onChange={setDueDate}
                  placeholder={t("bulkEdit.dueDatePlaceholder")}
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="assignment">
            <AccordionTrigger>{t("bulkEdit.assignmentSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label>{t("bulkEdit.assigneesLabel")}</Label>
                <AssigneeSelector
                  selectedIds={assigneeIds}
                  options={userOptions}
                  onChange={setAssigneeIds}
                  emptyMessage={t("bulkEdit.noUsersAvailable")}
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="details">
            <AccordionTrigger>{t("bulkEdit.detailsSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label htmlFor="bulk-status">{t("bulkEdit.statusLabel")}</Label>
                <Select value={statusId} onValueChange={setStatusId}>
                  <SelectTrigger id="bulk-status">
                    <SelectValue placeholder={t("bulkEdit.selectStatus")} />
                  </SelectTrigger>
                  <SelectContent>
                    {taskStatuses.map((status) => (
                      <SelectItem key={status.id} value={String(status.id)}>
                        {status.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="bulk-priority">{t("bulkEdit.priorityLabel")}</Label>
                <Select value={priority} onValueChange={setPriority}>
                  <SelectTrigger id="bulk-priority">
                    <SelectValue placeholder={t("bulkEdit.selectPriority")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">{t("priority.low")}</SelectItem>
                    <SelectItem value="medium">{t("priority.medium")}</SelectItem>
                    <SelectItem value="high">{t("priority.high")}</SelectItem>
                    <SelectItem value="urgent">{t("priority.urgent")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="recurrence">
            <AccordionTrigger>{t("bulkEdit.recurrenceSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label>{t("bulkEdit.recurringSchedule")}</Label>
                <TaskRecurrenceSelector
                  recurrence={recurrence}
                  onChange={setRecurrence}
                  strategy={recurrenceStrategy}
                  onStrategyChange={setRecurrenceStrategy}
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        <DialogFooter className="mt-6">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={isSubmitting}>
            {t("common:cancel")}
          </Button>
          <Button type="submit" disabled={!hasChanges || isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("bulkEdit.applying")}
              </>
            ) : (
              t("bulkEdit.applyChanges")
            )}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
};
