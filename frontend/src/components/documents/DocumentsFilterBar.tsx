import { ChevronDown, Filter } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TagPicker } from "@/components/tags/TagPicker";
import type { InitiativeRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";

const INITIATIVE_FILTER_ALL = "all";

export interface DocumentsFilterBarProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  initiativeFilter: string;
  onInitiativeFilterChange: (value: string) => void;
  lockedInitiativeId: number | null;
  lockedInitiativeName: string | null;
  viewableInitiatives: InitiativeRead[];
  initiativesLoading: boolean;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  viewMode: "grid" | "list" | "tags";
  tagFilters: TagSummary[];
  onTagFiltersChange: (tags: TagSummary[]) => void;
  fixedTagIds?: number[];
}

export const DocumentsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  initiativeFilter,
  onInitiativeFilterChange,
  lockedInitiativeId,
  lockedInitiativeName,
  viewableInitiatives,
  initiativesLoading,
  filtersOpen,
  onFiltersOpenChange,
  viewMode,
  tagFilters,
  onTagFiltersChange,
  fixedTagIds,
}: DocumentsFilterBarProps) => {
  const { t } = useTranslation("documents");

  return (
    <Collapsible open={filtersOpen} onOpenChange={onFiltersOpenChange} className="space-y-2">
      <div className="flex items-center justify-between sm:hidden">
        <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
          <Filter className="h-4 w-4" />
          {t("page.filters")}
        </div>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-3">
            {filtersOpen ? t("page.hideFilters") : t("page.showFilters")}
            <ChevronDown
              className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent forceMount className="data-[state=closed]:hidden">
        <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
          <div className="w-full space-y-2 sm:flex-1">
            <Label
              htmlFor="document-search"
              className="text-muted-foreground block text-xs font-medium"
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
          {lockedInitiativeId ? (
            <div className="w-full space-y-2 sm:w-60">
              <Label className="text-muted-foreground block text-xs font-medium">
                {t("page.initiativeLabel")}
              </Label>
              <p className="text-sm font-medium">
                {lockedInitiativeName ?? t("page.selectedInitiative")}
              </p>
            </div>
          ) : (
            <div className="w-full space-y-2 sm:w-60">
              <Label
                htmlFor="document-initiative-filter"
                className="text-muted-foreground block text-xs font-medium"
              >
                {t("page.initiativeLabel")}
              </Label>
              <Select
                value={initiativeFilter}
                onValueChange={(value) => onInitiativeFilterChange(value)}
                disabled={initiativesLoading}
              >
                <SelectTrigger id="document-initiative-filter">
                  <SelectValue placeholder={t("page.allInitiatives")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={INITIATIVE_FILTER_ALL}>{t("page.allInitiatives")}</SelectItem>
                  {viewableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {viewMode !== "tags" && !fixedTagIds && (
            <div className="w-full space-y-2 sm:w-48">
              <Label
                htmlFor="document-tag-filter"
                className="text-muted-foreground block text-xs font-medium"
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
      </CollapsibleContent>
    </Collapsible>
  );
};
