import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  GuildRead,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { PRIORITY_ORDER } from "@/lib/sorting";

interface GlobalTaskFiltersProps {
  statusFilters: TaskStatusCategory[];
  setStatusFilters: (filters: TaskStatusCategory[]) => void;
  priorityFilters: TaskPriority[];
  setPriorityFilters: (filters: TaskPriority[]) => void;
  guildFilters: number[];
  setGuildFilters: (filters: number[]) => void;
  propertyFilters: PropertyFilterCondition[];
  setPropertyFilters: (filters: PropertyFilterCondition[]) => void;
  filtersOpen: boolean;
  setFiltersOpen: (open: boolean) => void;
  guilds: GuildRead[];
  /** Resets every filter back to this page's baseline selection. */
  onClear?: () => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
}

export const GlobalTaskFilters = ({
  statusFilters,
  setStatusFilters,
  priorityFilters,
  setPriorityFilters,
  guildFilters,
  setGuildFilters,
  propertyFilters,
  setPropertyFilters,
  filtersOpen,
  setFiltersOpen,
  guilds,
  onClear,
  activeCount,
}: GlobalTaskFiltersProps) => {
  const { t } = useTranslation("tasks");

  const statusOptions = useMemo(
    () => [
      { value: "backlog" as TaskStatusCategory, label: t("statusCategory.backlog") },
      { value: "todo" as TaskStatusCategory, label: t("statusCategory.todo") },
      { value: "in_progress" as TaskStatusCategory, label: t("statusCategory.in_progress") },
      { value: "done" as TaskStatusCategory, label: t("statusCategory.done") },
    ],
    [t]
  );

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={setFiltersOpen}
      title={t("filters.heading")}
      onClear={onClear}
      activeCount={activeCount}
    >
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full sm:w-60 lg:flex-1">
          <Label
            htmlFor="task-status-filter"
            className="mb-2 block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByStatusCategory")}
          </Label>
          <MultiSelect
            selectedValues={statusFilters}
            options={statusOptions.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            onChange={(values) => setStatusFilters(values as TaskStatusCategory[])}
            placeholder={t("filters.allStatusCategories")}
            emptyMessage={t("filters.noStatusCategories")}
          />
        </div>
        <div className="w-full sm:w-60 lg:flex-1">
          <Label
            htmlFor="task-priority-filter"
            className="mb-2 block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByPriority")}
          </Label>
          <MultiSelect
            selectedValues={priorityFilters}
            options={PRIORITY_ORDER.map((priority) => ({
              value: priority,
              label: t(`priority.${priority}` as never),
            }))}
            onChange={(values) => setPriorityFilters(values as TaskPriority[])}
            placeholder={t("filters.allPriorities")}
            emptyMessage={t("filters.noPriorities")}
          />
        </div>
        <div className="w-full sm:w-60 lg:flex-1">
          <Label
            htmlFor="task-guild-filter"
            className="mb-2 block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByGuild")}
          </Label>
          <MultiSelect
            selectedValues={guildFilters.map(String)}
            options={guilds.map((guild) => ({
              value: String(guild.id),
              label: guild.name,
            }))}
            onChange={(values) => {
              const numericValues = values.map(Number).filter(Number.isFinite);
              setGuildFilters(numericValues);
            }}
            placeholder={t("filters.allGuilds")}
            emptyMessage={t("filters.noGuilds")}
          />
        </div>
      </div>
      <PropertyFilter value={propertyFilters} onChange={setPropertyFilters} />
    </ToolFilterPanel>
  );
};
