import { useTranslation } from "react-i18next";

import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type CountersFilterBarProps = {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets every filter this bar owns — offered in the mobile sheet. */
  onClear?: () => void;
};

export const CountersFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  filtersOpen,
  onFiltersOpenChange,
  onClear,
  activeCount,
}: CountersFilterBarProps) => {
  const { t } = useTranslation(["counterGroups", "common"]);

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
          <Label
            htmlFor="counter-group-search"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.filterByName")}
          </Label>
          <Input
            id="counter-group-search"
            placeholder={t("filters.searchGroups")}
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            className="min-w-60"
          />
        </div>
      </div>
    </ToolFilterPanel>
  );
};
