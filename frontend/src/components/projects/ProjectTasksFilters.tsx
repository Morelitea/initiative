import { useMemo } from "react";
import { useTranslation } from "react-i18next";

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
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import type { ProjectTaskStatus, Tag } from "@/types/api";

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
  const { t } = useTranslation("projects");

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTags = useMemo(() => {
    const tagMap = new Map(tags.map((tag) => [tag.id, tag]));
    return tagFilters.map((id) => tagMap.get(id)).filter((tag): tag is Tag => tag !== undefined);
  }, [tags, tagFilters]);

  const handleTagsChange = (newTags: TagSummary[]) => {
    onTagFiltersChange(newTags.map((tag) => tag.id));
  };

  return (
    <div className="border-muted bg-background/40 flex flex-wrap items-end gap-4 rounded-md border p-3">
      <div className="w-full space-y-2 sm:w-48">
        <Label
          htmlFor="assignee-filter"
          className="text-muted-foreground block text-xs font-medium"
        >
          {t("filters.filterByAssignee")}
        </Label>
        <MultiSelect
          selectedValues={assigneeFilters}
          options={userOptions.map((option) => ({
            value: String(option.id),
            label: option.label,
          }))}
          onChange={onAssigneeFiltersChange}
          placeholder={t("filters.allAssignees")}
          emptyMessage={t("filters.noUsersAvailable")}
        />
      </div>
      <div className="w-full space-y-2 sm:w-48">
        <Label htmlFor="due-filter" className="text-muted-foreground block text-xs font-medium">
          {t("filters.dueFilter")}
        </Label>
        <Select
          value={dueFilter}
          onValueChange={(value) => onDueFilterChange(value as DueFilterOption)}
        >
          <SelectTrigger id="due-filter">
            <SelectValue placeholder={t("filters.allDueDates")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("filters.allDueDates")}</SelectItem>
            <SelectItem value="overdue">{t("filters.overdue")}</SelectItem>
            <SelectItem value="today">{t("filters.dueToday")}</SelectItem>
            <SelectItem value="7_days">{t("filters.dueNext7Days")}</SelectItem>
            <SelectItem value="30_days">{t("filters.dueNext30Days")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {viewMode === "table" || viewMode === "calendar" || viewMode === "gantt" ? (
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="status-filter"
            className="text-muted-foreground block text-xs font-medium"
          >
            {t("filters.filterByStatus")}
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
            placeholder={t("filters.allStatuses")}
            emptyMessage={t("filters.noStatusesAvailable")}
          />
        </div>
      ) : null}
      <div className="w-full space-y-2 sm:w-48">
        <Label htmlFor="tag-filter" className="text-muted-foreground block text-xs font-medium">
          {t("filters.filterByTag")}
        </Label>
        <TagPicker
          selectedTags={selectedTags}
          onChange={handleTagsChange}
          placeholder={t("filters.allTags")}
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
          {t("filters.showArchived")}
        </Label>
      </div>
    </div>
  );
};
