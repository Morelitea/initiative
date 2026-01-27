import { FormEvent, useState } from "react";
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
        <DialogTitle>Edit tasks</DialogTitle>
        <DialogDescription>
          Apply changes to {selectedTasks.length} selected task
          {selectedTasks.length === 1 ? "" : "s"}. Only fields you set will be updated.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={handleSubmit}>
        <Accordion type="single" collapsible className="w-full">
          <AccordionItem value="dates">
            <AccordionTrigger>Dates</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label htmlFor="bulk-start-date">Start date</Label>
                <DateTimePicker
                  value={startDate}
                  onChange={setStartDate}
                  placeholder="Set start date"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bulk-due-date">Due date</Label>
                <DateTimePicker value={dueDate} onChange={setDueDate} placeholder="Set due date" />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="assignment">
            <AccordionTrigger>Assignment</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label>Assignees</Label>
                <AssigneeSelector
                  selectedIds={assigneeIds}
                  options={userOptions}
                  onChange={setAssigneeIds}
                  emptyMessage="No users available"
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="details">
            <AccordionTrigger>Details</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label htmlFor="bulk-status">Status</Label>
                <Select value={statusId} onValueChange={setStatusId}>
                  <SelectTrigger id="bulk-status">
                    <SelectValue placeholder="Select status" />
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
                <Label htmlFor="bulk-priority">Priority</Label>
                <Select value={priority} onValueChange={setPriority}>
                  <SelectTrigger id="bulk-priority">
                    <SelectValue placeholder="Select priority" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="urgent">Urgent</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="recurrence">
            <AccordionTrigger>Recurrence</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label>Recurring schedule</Label>
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
            Cancel
          </Button>
          <Button type="submit" disabled={!hasChanges || isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Applying…
              </>
            ) : (
              "Apply changes"
            )}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
};
