import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { TagPicker } from "@/components/tags/TagPicker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface DocumentsFilterBarProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  viewMode: "grid" | "list" | "tags";
  tagFilters: TagSummary[];
  onTagFiltersChange: (tags: TagSummary[]) => void;
  fixedTagIds?: number[];
  propertyFilters: PropertyFilterCondition[];
  onPropertyFiltersChange: (next: PropertyFilterCondition[]) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets search, tags, and property conditions — offered in the sheet. */
  onClear?: () => void;
}

export const DocumentsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  filtersOpen,
  onFiltersOpenChange,
  viewMode,
  tagFilters,
  onTagFiltersChange,
  fixedTagIds,
  propertyFilters,
  onPropertyFiltersChange,
  onClear,
  activeCount,
}: DocumentsFilterBarProps) => {
  const { t } = useTranslation("documents");

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={onFiltersOpenChange}
      title={t("page.filters")}
      onClear={onClear}
      activeCount={activeCount}
    >
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 sm:flex-1">
          <Label
            htmlFor="document-search"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("page.searchLabel")}
          </Label>
          <Input
            id="document-search"
            type="search"
            placeholder={t("page.searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
          />
        </div>
        {viewMode !== "tags" && !fixedTagIds && (
          <div className="w-full space-y-2 sm:w-48">
            <Label
              htmlFor="document-tag-filter"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("page.filterByTag")}
            </Label>
            <TagPicker
              selectedTags={tagFilters}
              onChange={onTagFiltersChange}
              placeholder={t("page.allTags")}
              variant="filter"
            />
          </div>
        )}
      </div>
      <PropertyFilter value={propertyFilters} onChange={onPropertyFiltersChange} />
    </ToolFilterPanel>
  );
};
