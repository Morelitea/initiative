import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { DueFilterOption, UserOption } from "@/components/projects/projectTasksConfig";
import type { ProjectTaskStatus } from "@/types/api";

export type ListStatusFilter = "all" | "incomplete" | number;

type ProjectTasksFiltersProps = {
  viewMode: "kanban" | "table" | "calendar" | "gantt";
  userOptions: UserOption[];
  taskStatuses: ProjectTaskStatus[];
  assigneeFilter: "all" | string;
  dueFilter: DueFilterOption;
  listStatusFilter: ListStatusFilter;
  onAssigneeFilterChange: (value: string) => void;
  onDueFilterChange: (value: DueFilterOption) => void;
  onListStatusFilterChange: (value: ListStatusFilter) => void;
};

export const ProjectTasksFilters = ({
  viewMode,
  taskStatuses,
  userOptions,
  assigneeFilter,
  dueFilter,
  listStatusFilter,
  onAssigneeFilterChange,
  onDueFilterChange,
  onListStatusFilterChange,
}: ProjectTasksFiltersProps) => (
  <div className="border-muted bg-background/40 flex flex-wrap items-end gap-4 rounded-md border p-3">
    <div className="w-full sm:w-48">
      <Label htmlFor="assignee-filter" className="text-muted-foreground text-xs font-medium">
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
      <Label htmlFor="due-filter" className="text-muted-foreground text-xs font-medium">
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
    {viewMode === "table" || viewMode === "calendar" || viewMode === "gantt" ? (
      <div className="w-full sm:w-44">
        <Label htmlFor="status-filter" className="text-muted-foreground text-xs font-medium">
          Filter by status
        </Label>
        <Select
          value={
            listStatusFilter === "all" || listStatusFilter === "incomplete"
              ? listStatusFilter
              : String(listStatusFilter)
          }
          onValueChange={(value) => {
            if (value === "all" || value === "incomplete") {
              onListStatusFilterChange(value);
              return;
            }
            const parsed = Number(value);
            if (Number.isFinite(parsed)) {
              onListStatusFilterChange(parsed);
            }
          }}
        >
          <SelectTrigger id="status-filter">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="incomplete">Incomplete</SelectItem>
            {taskStatuses.map((status) => (
              <SelectItem key={status.id} value={String(status.id)}>
                {status.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    ) : null}
  </div>
);
