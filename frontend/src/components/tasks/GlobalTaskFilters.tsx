import { useTranslation } from "react-i18next";

import type {
  CommunityRead,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { TaskStatusPriorityFilters } from "@/components/tasks/TaskStatusPriorityFilters";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";

interface GlobalTaskFiltersProps {
  statusFilters: TaskStatusCategory[];
  setStatusFilters: (filters: TaskStatusCategory[]) => void;
  priorityFilters: TaskPriority[];
  setPriorityFilters: (filters: TaskPriority[]) => void;
  communityFilters: number[];
  setCommunityFilters: (filters: number[]) => void;
  propertyFilters: PropertyFilterCondition[];
  setPropertyFilters: (filters: PropertyFilterCondition[]) => void;
  filtersOpen: boolean;
  setFiltersOpen: (open: boolean) => void;
  communities: CommunityRead[];
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
  communityFilters,
  setCommunityFilters,
  propertyFilters,
  setPropertyFilters,
  filtersOpen,
  setFiltersOpen,
  communities,
  onClear,
  activeCount,
}: GlobalTaskFiltersProps) => {
  const { t } = useTranslation("tasks");

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={setFiltersOpen}
      onClear={onClear}
      activeCount={activeCount}
    >
      <div className="flex flex-wrap items-end gap-4">
        <TaskStatusPriorityFilters
          statusFilters={statusFilters}
          onStatusChange={setStatusFilters}
          priorityFilters={priorityFilters}
          onPriorityChange={setPriorityFilters}
        />
        <div className="w-full medium:w-60 expanded:flex-1">
          <Label
            htmlFor="task-community-filter"
            className="mb-2 block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByCommunity")}
          </Label>
          <MultiSelect
            selectedValues={communityFilters.map(String)}
            options={communities.map((community) => ({
              value: String(community.id),
              label: community.name,
            }))}
            onChange={(values) => {
              const numericValues = values.map(Number).filter(Number.isFinite);
              setCommunityFilters(numericValues);
            }}
            placeholder={t("filters.allCommunities")}
            emptyMessage={t("filters.noCommunities")}
          />
        </div>
      </div>
      <PropertyFilter value={propertyFilters} onChange={setPropertyFilters} />
    </ToolFilterPanel>
  );
};
