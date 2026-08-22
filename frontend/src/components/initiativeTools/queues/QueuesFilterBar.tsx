import { useTranslation } from "react-i18next";

import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type StatusFilter = "all" | "active" | "inactive";

type QueuesFilterBarProps = {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (value: StatusFilter) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets every filter this bar owns — offered in the mobile sheet. */
  onClear?: () => void;
};

export const QueuesFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  statusFilter,
  onStatusFilterChange,
  filtersOpen,
  onFiltersOpenChange,
  onClear,
  activeCount,
}: QueuesFilterBarProps) => {
  const { t } = useTranslation(["queues", "common"]);

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={onFiltersOpenChange}
      title={t("filters.heading")}
      onClear={onClear}
      activeCount={activeCount}
    >
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 lg:flex-1">
          <Label htmlFor="queue-search" className="block font-medium text-muted-foreground text-xs">
            {t("filters.filterByName")}
          </Label>
          <Input
            id="queue-search"
            placeholder={t("filters.searchQueues")}
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            className="min-w-60"
          />
        </div>
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="queue-status-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.status")}
          </Label>
          <Select
            value={statusFilter}
            onValueChange={(value) => onStatusFilterChange(value as StatusFilter)}
          >
            <SelectTrigger id="queue-status-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("filters.allStatuses")}</SelectItem>
              <SelectItem value="active">{t("filters.activeOnly")}</SelectItem>
              <SelectItem value="inactive">{t("filters.inactiveOnly")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </ToolFilterPanel>
  );
};
