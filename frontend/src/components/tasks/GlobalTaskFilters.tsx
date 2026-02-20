import { useMemo } from "react";
import { ChevronDown, Filter } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { TaskPriority, TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";
import type { Guild } from "@/types/api";

const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];

interface GlobalTaskFiltersProps {
  statusFilters: TaskStatusCategory[];
  setStatusFilters: (filters: TaskStatusCategory[]) => void;
  priorityFilters: TaskPriority[];
  setPriorityFilters: (filters: TaskPriority[]) => void;
  guildFilters: number[];
  setGuildFilters: (filters: number[]) => void;
  filtersOpen: boolean;
  setFiltersOpen: (open: boolean) => void;
  guilds: Guild[];
}

export const GlobalTaskFilters = ({
  statusFilters,
  setStatusFilters,
  priorityFilters,
  setPriorityFilters,
  guildFilters,
  setGuildFilters,
  filtersOpen,
  setFiltersOpen,
  guilds,
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
    <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
      <div className="flex items-center justify-between sm:hidden">
        <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
          <Filter className="h-4 w-4" />
          {t("filters.heading")}
        </div>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-3">
            {filtersOpen ? t("filters.hide") : t("filters.show")}
            <ChevronDown
              className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent forceMount className="data-[state=closed]:hidden">
        <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
          <div className="w-full sm:w-60 lg:flex-1">
            <Label
              htmlFor="task-status-filter"
              className="text-muted-foreground mb-2 block text-xs font-medium"
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
              className="text-muted-foreground mb-2 block text-xs font-medium"
            >
              {t("filters.filterByPriority")}
            </Label>
            <MultiSelect
              selectedValues={priorityFilters}
              options={priorityOrder.map((priority) => ({
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
              className="text-muted-foreground mb-2 block text-xs font-medium"
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
      </CollapsibleContent>
    </Collapsible>
  );
};
