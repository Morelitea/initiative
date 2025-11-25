import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { DueFilterOption, UserOption } from "@/components/projects/projectTasksConfig";
import { taskStatusOrder } from "@/components/projects/projectTasksConfig";
import type { TaskStatus } from "@/types/api";

type ProjectTasksFiltersProps = {
  viewMode: "kanban" | "list" | "calendar" | "gantt";
  userOptions: UserOption[];
  assigneeFilter: "all" | string;
  dueFilter: DueFilterOption;
  listStatusFilter: "all" | "incomplete" | TaskStatus;
  onAssigneeFilterChange: (value: string) => void;
  onDueFilterChange: (value: DueFilterOption) => void;
  onListStatusFilterChange: (value: "all" | "incomplete" | TaskStatus) => void;
};

export const ProjectTasksFilters = ({
  viewMode,
  userOptions,
  assigneeFilter,
  dueFilter,
  listStatusFilter,
  onAssigneeFilterChange,
  onDueFilterChange,
  onListStatusFilterChange,
}: ProjectTasksFiltersProps) => (
  <div className="flex flex-wrap items-end gap-4 rounded-md border border-muted bg-background/40 p-3">
    <div className="w-full sm:w-48">
      <Label htmlFor="assignee-filter" className="text-xs font-medium text-muted-foreground">
        Filter by assignee
      </Label>
      <Select value={assigneeFilter} onValueChange={onAssigneeFilterChange}>
        <SelectTrigger id="assignee-filter">
          <SelectValue placeholder="All assignees" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All assignees</SelectItem>
          {userOptions.map((option) => (
            <SelectItem key={option.id} value={String(option.id)}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
    <div className="w-full sm:w-48">
      <Label htmlFor="due-filter" className="text-xs font-medium text-muted-foreground">
        Due filter
      </Label>
      <Select
        value={dueFilter}
        onValueChange={(value) => onDueFilterChange(value as DueFilterOption)}
      >
        <SelectTrigger id="due-filter">
          <SelectValue placeholder="All due dates" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All due dates</SelectItem>
          <SelectItem value="overdue">Overdue</SelectItem>
          <SelectItem value="today">Due today</SelectItem>
          <SelectItem value="7_days">Due next 7 days</SelectItem>
          <SelectItem value="30_days">Due next 30 days</SelectItem>
        </SelectContent>
      </Select>
    </div>
    {viewMode === "list" ? (
      <div className="w-full sm:w-44">
        <Label htmlFor="status-filter" className="text-xs font-medium text-muted-foreground">
          Filter by status
        </Label>
        <Select
          value={listStatusFilter}
          onValueChange={(value) =>
            onListStatusFilterChange(value as "all" | "incomplete" | TaskStatus)
          }
        >
          <SelectTrigger id="status-filter">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="incomplete">Incomplete</SelectItem>
            {taskStatusOrder.map((status) => (
              <SelectItem key={status} value={status}>
                {status.replace("_", " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    ) : null}
  </div>
);
