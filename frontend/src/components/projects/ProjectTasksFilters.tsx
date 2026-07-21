import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TagRead, TagSummary, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import type { DueFilterOption } from "@/components/projects/projectTasksConfig";
import {
  PropertyFilter,
  type PropertyFilterCondition,
} from "@/components/properties/PropertyFilter";
import { TagPicker } from "@/components/tags/TagPicker";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type ListStatusFilter = "all" | "incomplete" | number;

type ProjectTasksFiltersProps = {
  projectId: number;
  taskStatuses: TaskStatusRead[];
  tags: TagRead[];
  assigneeFilters: string[];
  dueFilter: DueFilterOption;
  statusFilters: number[];
  tagFilters: number[];
  propertyFilters: PropertyFilterCondition[];
  showArchived: boolean;
  onAssigneeFiltersChange: (values: string[]) => void;
  onDueFilterChange: (value: DueFilterOption) => void;
  onStatusFiltersChange: (values: number[]) => void;
  onTagFiltersChange: (values: number[]) => void;
  onPropertyFiltersChange: (values: PropertyFilterCondition[]) => void;
  onShowArchivedChange: (value: boolean) => void;
};

export const ProjectTasksFilters = ({
  taskStatuses,
  projectId,
  tags,
  assigneeFilters,
  dueFilter,
  statusFilters,
  tagFilters,
  propertyFilters,
  showArchived,
  onAssigneeFiltersChange,
  onDueFilterChange,
  onStatusFiltersChange,
  onTagFiltersChange,
  onPropertyFiltersChange,
  onShowArchivedChange,
}: ProjectTasksFiltersProps) => {
  const { t } = useTranslation("projects");

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTags = useMemo(() => {
    const tagMap = new Map(tags.map((tag) => [tag.id, tag]));
    return tagFilters
      .map((id) => tagMap.get(id))
      .filter((tag): tag is TagRead => tag !== undefined);
  }, [tags, tagFilters]);

  const handleTagsChange = (newTags: TagSummary[]) => {
    onTagFiltersChange(newTags.map((tag) => tag.id));
  };

  return (
    <div className="flex flex-col gap-4 rounded-md border border-muted bg-background/40 p-3">
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="assignee-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByAssignee")}
          </Label>
          <MemberMultiSelect
            variant="filter"
            scope={{ type: "project", projectId }}
            selectedIds={assigneeFilters.map(Number).filter(Number.isFinite)}
            onChange={(ids) => onAssigneeFiltersChange(ids.map(String))}
            placeholder={t("filters.allAssignees")}
            emptyMessage={t("filters.noUsersAvailable")}
          />
        </div>
        <div className="w-full space-y-2 sm:w-48">
          <Label htmlFor="due-filter" className="block font-medium text-muted-foreground text-xs">
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
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="status-filter"
            className="block font-medium text-muted-foreground text-xs"
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

        <div className="w-full space-y-2 sm:w-48">
          <Label htmlFor="tag-filter" className="block font-medium text-muted-foreground text-xs">
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
          <Label htmlFor="show-archived" className="cursor-pointer font-medium text-sm">
            {t("filters.showArchived")}
          </Label>
        </div>
      </div>
      <PropertyFilter value={propertyFilters} onChange={onPropertyFiltersChange} />
    </div>
  );
};
