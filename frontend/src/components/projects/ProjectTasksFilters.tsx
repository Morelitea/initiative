import { useMemo } from "react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "@/components/ui/multi-select";
import { Checkbox } from "@/components/ui/checkbox";
import { TagPicker } from "@/components/tags/TagPicker";
import type { DueFilterOption, UserOption } from "@/components/projects/projectTasksConfig";
import type { ProjectTaskStatus, Tag, TagSummary } from "@/types/api";

export type ListStatusFilter = "all" | "incomplete" | number;

type ProjectTasksFiltersProps = {
  viewMode: "kanban" | "table" | "calendar" | "gantt";
  userOptions: UserOption[];
  taskStatuses: ProjectTaskStatus[];
  tags: Tag[];
  assigneeFilters: string[];
  dueFilter: DueFilterOption;
  statusFilters: number[];
  tagFilters: number[];
  showArchived: boolean;
  onAssigneeFiltersChange: (values: string[]) => void;
  onDueFilterChange: (value: DueFilterOption) => void;
  onStatusFiltersChange: (values: number[]) => void;
  onTagFiltersChange: (values: number[]) => void;
  onShowArchivedChange: (value: boolean) => void;
};

export const ProjectTasksFilters = ({
  viewMode,
  taskStatuses,
  userOptions,
  tags,
  assigneeFilters,
  dueFilter,
  statusFilters,
  tagFilters,
  showArchived,
  onAssigneeFiltersChange,
  onDueFilterChange,
  onStatusFiltersChange,
  onTagFiltersChange,
  onShowArchivedChange,
}: ProjectTasksFiltersProps) => {
  // Convert tag IDs to Tag objects for TagPicker
  const selectedTags = useMemo(() => {
    const tagMap = new Map(tags.map((t) => [t.id, t]));
    return tagFilters.map((id) => tagMap.get(id)).filter((t): t is Tag => t !== undefined);
  }, [tags, tagFilters]);

  const handleTagsChange = (newTags: TagSummary[]) => {
    onTagFiltersChange(newTags.map((t) => t.id));
  };

  return (
    <div className="border-muted bg-background/40 flex flex-wrap items-end gap-4 rounded-md border p-3">
      <div className="w-full sm:w-48">
        <Label
          htmlFor="assignee-filter"
          className="text-muted-foreground mb-2 block text-xs font-medium"
        >
          Filter by assignee
        </Label>
        <MultiSelect
          selectedValues={assigneeFilters}
          options={userOptions.map((option) => ({
            value: String(option.id),
            label: option.label,
          }))}
          onChange={onAssigneeFiltersChange}
          placeholder="All assignees"
          emptyMessage="No users available"
        />
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
        <div className="w-full sm:w-48">
          <Label
            htmlFor="status-filter"
            className="text-muted-foreground mb-2 block text-xs font-medium"
          >
            Filter by status
          </Label>
          <MultiSelect
            selectedValues={statusFilters.map(String)}
            options={taskStatuses.map((status) => ({
              value: String(status.id),
              label: status.name,
            }))}
            onChange={(values) => {
              const numericValues = values.map(Number).filter(Number.isFinite);
              onStatusFiltersChange(numericValues);
            }}
            placeholder="All statuses"
            emptyMessage="No statuses available"
          />
        </div>
      ) : null}
      <div className="w-full sm:w-48">
        <Label
          htmlFor="tag-filter"
          className="text-muted-foreground mb-2 block text-xs font-medium"
        >
          Filter by tag
        </Label>
        <TagPicker
          selectedTags={selectedTags}
          onChange={handleTagsChange}
          placeholder="All tags"
          variant="filter"
        />
      </div>
      <div className="flex items-center gap-2 self-center pt-4 sm:pt-0">
        <Checkbox
          id="show-archived"
          checked={showArchived}
          onCheckedChange={(checked) => onShowArchivedChange(checked === true)}
        />
        <Label htmlFor="show-archived" className="cursor-pointer text-sm font-medium">
          Show archived
        </Label>
      </div>
    </div>
  );
};
