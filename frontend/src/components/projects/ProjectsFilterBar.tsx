import { ChevronDown, Filter } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagPicker } from "@/components/tags/TagPicker";
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
import { Switch } from "@/components/ui/switch";

const INITIATIVE_FILTER_ALL = "all";

type ProjectsFilterBarProps = {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  initiativeFilter: string;
  onInitiativeFilterChange: (value: string) => void;
  lockedInitiativeId: number | null;
  lockedInitiativeName: string | null;
  viewableInitiatives: InitiativeRead[];
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  sortMode: "custom" | "updated" | "created" | "alphabetical" | "recently_viewed";
  onSortModeChange: (
    value: "custom" | "updated" | "created" | "alphabetical" | "recently_viewed"
  ) => void;
  favoritesOnly: boolean;
  onFavoritesOnlyChange: (value: boolean) => void;
  tagFilters: TagSummary[];
  onTagFiltersChange: (tags: TagSummary[]) => void;
  fixedTagIds?: number[];
};

export const ProjectsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  initiativeFilter,
  onInitiativeFilterChange,
  lockedInitiativeId,
  lockedInitiativeName,
  viewableInitiatives,
  filtersOpen,
  onFiltersOpenChange,
  sortMode,
  onSortModeChange,
  favoritesOnly,
  onFavoritesOnlyChange,
  tagFilters,
  onTagFiltersChange,
  fixedTagIds,
}: ProjectsFilterBarProps) => {
  const { t } = useTranslation(["projects", "common"]);

  return (
    <Collapsible open={filtersOpen} onOpenChange={onFiltersOpenChange} className="space-y-2">
      <div className="flex items-center justify-between sm:hidden">
        <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
          <Filter className="h-4 w-4" />
          {t("filters.heading")}
        </div>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 px-3">
            {filtersOpen ? t("filters.hide") : t("filters.show")}
            <ChevronDown
              className={`h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
            />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent forceMount className="data-[state=closed]:hidden">
        <div className="mt-2 flex flex-wrap items-end gap-4 rounded-md border border-muted bg-background/40 p-3 sm:mt-0">
          <div className="w-full space-y-2 lg:flex-1">
            <Label
              htmlFor="project-search"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("filters.filterByName")}
            </Label>
            <Input
              id="project-search"
              placeholder={t("filters.searchProjects")}
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
              className="min-w-60"
            />
          </div>
          {lockedInitiativeId ? (
            <div className="w-full space-y-2 sm:w-60">
              <Label className="block font-medium text-muted-foreground text-xs">
                {t("filters.initiative")}
              </Label>
              <p className="font-medium text-sm">
                {lockedInitiativeName ?? t("filters.selectedInitiative")}
              </p>
            </div>
          ) : (
            <div className="w-full space-y-2 sm:w-60">
              <Label
                htmlFor="project-initiative-filter"
                className="block font-medium text-muted-foreground text-xs"
              >
                {t("filters.filterByInitiative")}
              </Label>
              <Select value={initiativeFilter} onValueChange={onInitiativeFilterChange}>
                <SelectTrigger id="project-initiative-filter">
                  <SelectValue placeholder={t("filters.allInitiatives")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={INITIATIVE_FILTER_ALL}>
                    {t("filters.allInitiatives")}
                  </SelectItem>
                  {viewableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={initiative.id.toString()}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {!fixedTagIds && (
            <div className="w-full space-y-2 sm:w-48">
              <Label
                htmlFor="tag-filter"
                className="block font-medium text-muted-foreground text-xs"
              >
                {t("filters.filterByTag")}
              </Label>
              <TagPicker
                selectedTags={tagFilters}
                onChange={onTagFiltersChange}
                placeholder={t("filters.allTags")}
                variant="filter"
              />
            </div>
          )}
          <div className="w-full space-y-2 sm:w-60">
            <Label
              htmlFor="project-sort"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("filters.sortProjects")}
            </Label>
            <Select
              value={sortMode}
              onValueChange={(value) =>
                onSortModeChange(
                  value as "custom" | "updated" | "created" | "alphabetical" | "recently_viewed"
                )
              }
            >
              <SelectTrigger id="project-sort">
                <SelectValue placeholder={t("filters.selectSortOrder")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="custom">{t("filters.sortCustom")}</SelectItem>
                <SelectItem value="recently_viewed">{t("filters.sortRecentlyOpened")}</SelectItem>
                <SelectItem value="updated">{t("filters.sortRecentlyUpdated")}</SelectItem>
                <SelectItem value="created">{t("filters.sortRecentlyCreated")}</SelectItem>
                <SelectItem value="alphabetical">{t("filters.sortAlphabetical")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="w-full space-y-2 sm:w-60">
            <Label
              htmlFor="favorites-only"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("filters.favorites")}
            </Label>
            <div className="flex h-10 items-center gap-3 rounded-md border bg-background/60 px-3">
              <Switch
                id="favorites-only"
                checked={favoritesOnly}
                onCheckedChange={(checked) => onFavoritesOnlyChange(Boolean(checked))}
                aria-label={t("filters.showOnlyFavorites")}
              />
              <span className="text-muted-foreground text-sm">
                {t("filters.showOnlyFavorites")}
              </span>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
