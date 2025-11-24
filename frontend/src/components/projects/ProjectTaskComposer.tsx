import { FormEvent } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../ui/accordion";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Textarea } from "../ui/textarea";
import { DateTimePicker } from "../ui/date-time-picker";
import type { TaskPriority } from "../../types/api";
import { AssigneeSelector } from "./AssigneeSelector";

interface ProjectTaskComposerProps {
  title: string;
  description: string;
  priority: TaskPriority;
  assigneeIds: number[];
  dueDate: string;
  canWrite: boolean;
  isArchived: boolean;
  isSubmitting: boolean;
  hasError: boolean;
  users: { id: number; label: string }[];
  onTitleChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onPriorityChange: (value: TaskPriority) => void;
  onAssigneesChange: (value: number[]) => void;
  onDueDateChange: (value: string) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  autoFocusTitle?: boolean;
}

export const ProjectTaskComposer = ({
  title,
  description,
  priority,
  assigneeIds,
  dueDate,
  canWrite,
  isArchived,
  isSubmitting,
  hasError,
  users,
  onTitleChange,
  onDescriptionChange,
  onPriorityChange,
  onAssigneesChange,
  onDueDateChange,
  onSubmit,
  onCancel,
  autoFocusTitle = false,
}: ProjectTaskComposerProps) => {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Create task</CardTitle>
        <CardDescription>
          Add work to the board. Only people with write access can create tasks.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isArchived ? (
          <p className="text-sm text-muted-foreground">
            This project is archived. Unarchive it to add new tasks.
          </p>
        ) : canWrite ? (
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="task-title">Title</Label>
              <Input
                id="task-title"
                value={title}
                onChange={(event) => onTitleChange(event.target.value)}
                placeholder="Draft launch plan"
                required
                autoFocus={autoFocusTitle}
              />
            </div>
            <Accordion type="single" collapsible>
              <AccordionItem value="advanced">
                <AccordionTrigger>Advanced details</AccordionTrigger>
                <AccordionContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="task-description">Description (Markdown supported)</Label>
                    <Textarea
                      id="task-description"
                      rows={3}
                      value={description}
                      onChange={(event) => onDescriptionChange(event.target.value)}
                      placeholder="Share context, links, or acceptance criteria."
                    />
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="task-priority">Priority</Label>
                      <Select
                        value={priority}
                        onValueChange={(value) => onPriorityChange(value as TaskPriority)}
                      >
                        <SelectTrigger id="task-priority">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="low">Low priority</SelectItem>
                          <SelectItem value="medium">Medium priority</SelectItem>
                          <SelectItem value="high">High priority</SelectItem>
                          <SelectItem value="urgent">Urgent</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Assignees</Label>
                      <AssigneeSelector
                        selectedIds={assigneeIds}
                        options={users}
                        onChange={onAssigneesChange}
                        disabled={isSubmitting}
                        emptyMessage="Invite initiative members to assign work."
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="task-due-date">Due date</Label>
                    <DateTimePicker
                      id="task-due-date"
                      value={dueDate}
                      onChange={onDueDateChange}
                      disabled={isSubmitting}
                      placeholder="Optional"
                    />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Saving…" : "Create task"}
              </Button>
              {onCancel ? (
                <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
                  Cancel
                </Button>
              ) : null}
              {hasError ? <p className="text-sm text-destructive">Unable to create task.</p> : null}
            </div>
          </form>
        ) : (
          <p className="text-sm text-muted-foreground">You need write access to create tasks.</p>
        )}
      </CardContent>
    </Card>
  );
};
