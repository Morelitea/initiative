import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  TagRead,
  TagSummary,
  TaskStatusCategory,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import {
  PropertyFilter,
  type PropertyFilterCondition,
} from "@/components/properties/PropertyFilter";
import { TagPicker } from "@/components/tags/TagPicker";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  ASSIGNEE_ME,
  ASSIGNEE_NONE,
  type DueToken,
  type TaskFilterSpec,
} from "@/lib/filters/taskFilters";

/**
 * Task statuses are per-project rows, so filtering by a status *id* only means
 * something inside one project. Categories are the stable vocabulary — which is
 * why a preset like "Incomplete" is expressed with them and survives being
 * shared or copied to another project.
 */
const STATUS_CATEGORIES: readonly TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];

/** Categories share one control with the statuses, so their values need a
 *  prefix that can't collide with a numeric status id. */
const CATEGORY_PREFIX = "category:";

type ProjectTasksFiltersProps = {
  projectId: number;
  taskStatuses: TaskStatusRead[];
  tags: TagRead[];
  /** The filter values, as one object — the same shape a preset holds. */
  value: TaskFilterSpec;
  onChange: (next: TaskFilterSpec) => void;
};

export const ProjectTasksFilters = ({
  taskStatuses,
  projectId,
  tags,
  value,
  onChange,
}: ProjectTasksFiltersProps) => {
  const { t } = useTranslation("projects");

  const patch = (fields: Partial<TaskFilterSpec>) => onChange({ ...value, ...fields });

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTags = useMemo(() => {
    const tagMap = new Map(tags.map((tag) => [tag.id, tag]));
    return value.tag_ids
      .map((id) => tagMap.get(id))
      .filter((tag): tag is TagRead => tag !== undefined);
  }, [tags, value.tag_ids]);

  const handleTagsChange = (newTags: TagSummary[]) => {
    patch({ tag_ids: newTags.map((tag) => tag.id) });
  };

  // `me` and `none` are resolved by the server per request, which is what
  // keeps a preset — and a link to it — meaning the same thing for everyone.
  // They are toggles rather than entries in the people picker, which only
  // knows real users.
  const assignedToMe = value.assignees.includes(ASSIGNEE_ME);
  const unassigned = value.assignees.includes(ASSIGNEE_NONE);
  const assigneeIds = value.assignees.filter(
    (entry) => entry !== ASSIGNEE_NONE && entry !== ASSIGNEE_ME
  );

  /** Rebuild the list, keeping the tokens ahead of the ids. */
  const setAssignees = (next: { me?: boolean; none?: boolean; ids?: string[] }) => {
    const me = next.me ?? assignedToMe;
    const none = next.none ?? unassigned;
    patch({
      assignees: [
        ...(none ? [ASSIGNEE_NONE] : []),
        ...(me ? [ASSIGNEE_ME] : []),
        ...(next.ids ?? assigneeIds),
      ],
    });
  };

  return (
    // Bare fields: the surrounding ToolFilterPanel supplies the box, the way it
    // does for every other filter bar.
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="assignee-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByAssignee")}
          </Label>
          <MemberMultiSelect
            id="assignee-filter"
            variant="filter"
            scope={{ type: "project", projectId }}
            selectedIds={assigneeIds.map(Number).filter(Number.isFinite)}
            onChange={(ids) => setAssignees({ ids: ids.map(String) })}
            tokens={[
              {
                value: ASSIGNEE_ME,
                label: t("filters.assignedToMe"),
                selected: assignedToMe,
                onToggle: (selected) => setAssignees({ me: selected }),
              },
              {
                value: ASSIGNEE_NONE,
                label: t("filters.unassigned"),
                selected: unassigned,
                onToggle: (selected) => setAssignees({ none: selected }),
              },
            ]}
            placeholder={t("filters.allAssignees")}
            emptyMessage={t("filters.noUsersAvailable")}
          />
        </div>
        <div className="w-full space-y-2 sm:w-48">
          <Label htmlFor="due-filter" className="block font-medium text-muted-foreground text-xs">
            {t("filters.dueFilter")}
          </Label>
          <Select
            value={value.due ?? "all"}
            onValueChange={(next) => patch({ due: next === "all" ? null : (next as DueToken) })}
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
            id="status-filter"
            selectedValues={[
              ...value.status_ids.map(String),
              ...value.status_categories.map((category) => `${CATEGORY_PREFIX}${category}`),
            ]}
            options={[
              ...taskStatuses.map((status) => ({
                value: String(status.id),
                label: status.name,
              })),
              ...STATUS_CATEGORIES.map((category) => ({
                value: `${CATEGORY_PREFIX}${category}`,
                label: t(`filters.category.${category}` as never),
                group: t("filters.statusCategory"),
              })),
            ]}
            onChange={(values) =>
              patch({
                status_ids: values
                  .filter((entry) => !entry.startsWith(CATEGORY_PREFIX))
                  .map(Number)
                  .filter(Number.isFinite),
                status_categories: values
                  .filter((entry) => entry.startsWith(CATEGORY_PREFIX))
                  .map((entry) => entry.slice(CATEGORY_PREFIX.length) as TaskStatusCategory),
              })
            }
            placeholder={t("filters.allStatuses")}
            emptyMessage={t("filters.noStatusesAvailable")}
          />
        </div>

        <div className="w-full space-y-2 sm:w-48">
          <Label htmlFor="tag-filter" className="block font-medium text-muted-foreground text-xs">
            {t("filters.filterByTag")}
          </Label>
          <TagPicker
            id="tag-filter"
            selectedTags={selectedTags}
            onChange={handleTagsChange}
            placeholder={t("filters.allTags")}
            variant="filter"
          />
        </div>
        <div className="w-full space-y-2 sm:w-60">
          <Label
            htmlFor="show-archived"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.archived")}
          </Label>
          <div className="flex h-9 items-center gap-3 rounded-md border bg-background/60 px-3">
            <Switch
              id="show-archived"
              checked={value.include_archived}
              onCheckedChange={(checked) => patch({ include_archived: Boolean(checked) })}
              aria-label={t("filters.showArchived")}
            />
            <span className="text-muted-foreground text-sm">{t("filters.showArchived")}</span>
          </div>
        </div>
      </div>
      <PropertyFilter
        value={value.properties}
        onChange={(properties: PropertyFilterCondition[]) => patch({ properties })}
      />
    </div>
  );
};
