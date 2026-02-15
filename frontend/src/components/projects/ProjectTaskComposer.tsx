import { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import type { TaskPriority, TaskRecurrence, TaskRecurrenceStrategy } from "@/types/api";
import { AssigneeSelector } from "@/components/projects/AssigneeSelector";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ProjectTaskComposerProps {
  title: string;
  description: string;
  priority: TaskPriority;
  assigneeIds: number[];
  startDate: string;
  dueDate: string;
  recurrence: TaskRecurrence | null;
  recurrenceStrategy: TaskRecurrenceStrategy;
  canWrite: boolean;
  isArchived: boolean;
  isSubmitting: boolean;
  hasError: boolean;
  users: { id: number; label: string }[];
  onTitleChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onPriorityChange: (value: TaskPriority) => void;
  onAssigneesChange: (value: number[]) => void;
  onStartDateChange: (value: string) => void;
  onDueDateChange: (value: string) => void;
  onRecurrenceChange: (value: TaskRecurrence | null) => void;
  onRecurrenceStrategyChange: (value: TaskRecurrenceStrategy) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  autoFocusTitle?: boolean;
}

export const ProjectTaskComposer = ({
  title,
  description,
  priority,
  assigneeIds,
  startDate,
  dueDate,
  recurrence,
  recurrenceStrategy,
  canWrite,
  isArchived,
  isSubmitting,
  hasError,
  users,
  onTitleChange,
  onDescriptionChange,
  onPriorityChange,
  onAssigneesChange,
  onStartDateChange,
  onDueDateChange,
  onRecurrenceChange,
  onRecurrenceStrategyChange,
  onSubmit,
  onCancel,
  autoFocusTitle = false,
}: ProjectTaskComposerProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const { data: roleLabels } = useRoleLabels();
  const memberLabel = getRoleLabel("member", roleLabels);
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <DialogContent className="bg-card max-h-screen overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{t("taskComposer.title")}</DialogTitle>
        <DialogDescription>{t("taskComposer.description")}</DialogDescription>
      </DialogHeader>
      <div>
        {isArchived ? (
          <p className="text-muted-foreground text-sm">{t("taskComposer.archivedMessage")}</p>
        ) : canWrite ? (
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="task-title">{t("taskComposer.titleLabel")}</Label>
              <Input
                id="task-title"
                value={title}
                onChange={(event) => onTitleChange(event.target.value)}
                placeholder={t("taskComposer.titlePlaceholder")}
                required
                autoFocus={autoFocusTitle}
              />
            </div>
            <Accordion type="single" collapsible>
              <AccordionItem value="advanced">
                <AccordionTrigger>{t("taskComposer.advancedDetails")}</AccordionTrigger>
                <AccordionContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="task-description">{t("taskComposer.descriptionLabel")}</Label>
                    <Textarea
                      id="task-description"
                      rows={3}
                      value={description}
                      onChange={(event) => onDescriptionChange(event.target.value)}
                      placeholder={t("taskComposer.descriptionPlaceholder")}
                    />
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="task-priority">{t("taskComposer.priorityLabel")}</Label>
                      <Select
                        value={priority}
                        onValueChange={(value) => onPriorityChange(value as TaskPriority)}
                      >
                        <SelectTrigger id="task-priority">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="low">{t("taskComposer.priorityLow")}</SelectItem>
                          <SelectItem value="medium">{t("taskComposer.priorityMedium")}</SelectItem>
                          <SelectItem value="high">{t("taskComposer.priorityHigh")}</SelectItem>
                          <SelectItem value="urgent">{t("taskComposer.priorityUrgent")}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>{t("taskComposer.assigneesLabel")}</Label>
                      <AssigneeSelector
                        selectedIds={assigneeIds}
                        options={users}
                        onChange={onAssigneesChange}
                        disabled={isSubmitting}
                        emptyMessage={t("taskComposer.assigneesEmptyMessage", { memberLabel })}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="task-start-date">{t("taskComposer.startDateLabel")}</Label>
                    <DateTimePicker
                      id="task-start-date"
                      value={startDate}
                      onChange={onStartDateChange}
                      disabled={isSubmitting}
                      placeholder={t("taskComposer.optional")}
                      calendarProps={{
                        hidden: {
                          after: new Date(dueDate),
                        },
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="task-due-date">{t("taskComposer.dueDateLabel")}</Label>
                    <DateTimePicker
                      id="task-due-date"
                      value={dueDate}
                      onChange={onDueDateChange}
                      disabled={isSubmitting}
                      placeholder={t("taskComposer.optional")}
                      calendarProps={{
                        hidden: {
                          before: new Date(startDate),
                        },
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <TaskRecurrenceSelector
                      recurrence={recurrence}
                      onChange={onRecurrenceChange}
                      strategy={recurrenceStrategy}
                      onStrategyChange={onRecurrenceStrategyChange}
                      disabled={isSubmitting}
                      referenceDate={dueDate || startDate}
                    />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? t("taskComposer.saving") : t("taskComposer.createTask")}
              </Button>
              {onCancel ? (
                <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
                  {t("common:cancel")}
                </Button>
              ) : null}
              {hasError ? (
                <p className="text-destructive text-sm">{t("taskComposer.createError")}</p>
              ) : null}
            </div>
          </form>
        ) : (
          <p className="text-muted-foreground text-sm">{t("taskComposer.noWriteAccess")}</p>
        )}
      </div>
    </DialogContent>
  );
};
