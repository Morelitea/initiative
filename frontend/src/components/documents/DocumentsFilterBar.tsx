import { ChevronDown, Filter } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
}: DocumentsFilterBarProps) => {
  const { t } = useTranslation("documents");

  return (
    <Collapsible open={filtersOpen} onOpenChange={onFiltersOpenChange} className="space-y-2">
      <div className="flex items-center justify-between sm:hidden">
        <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
          <Filter className="h-4 w-4" />
          {t("page.filters")}
        </div>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-3">
            {filtersOpen ? t("page.hideFilters") : t("page.showFilters")}
            <ChevronDown
              className={`h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent forceMount className="data-[state=closed]:hidden">
        <div className="mt-2 flex flex-col gap-3 rounded-md border border-muted bg-background/40 p-3 sm:mt-0">
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
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
