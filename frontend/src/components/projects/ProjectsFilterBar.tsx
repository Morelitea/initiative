import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { TagPicker } from "@/components/tags/TagPicker";
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
import type { ProjectSortMode } from "@/hooks/useProjectListView";

type ProjectsFilterBarProps = {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  sortMode: ProjectSortMode;
  onSortModeChange: (value: ProjectSortMode) => void;
  favoritesOnly: boolean;
  onFavoritesOnlyChange: (value: boolean) => void;
  tagFilters: TagSummary[];
  onTagFiltersChange: (tags: TagSummary[]) => void;
  fixedTagIds?: number[];
  /** Manual ordering is only offered where the list can actually be dragged. */
  allowCustomSort?: boolean;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets search, tags, and favorites — offered in the mobile sheet. */
  onClear?: () => void;
};

export const ProjectsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  filtersOpen,
  onFiltersOpenChange,
  sortMode,
  onSortModeChange,
  favoritesOnly,
  onFavoritesOnlyChange,
  tagFilters,
  onTagFiltersChange,
  fixedTagIds,
  allowCustomSort = true,
  onClear,
  activeCount,
}: ProjectsFilterBarProps) => {
  const { t } = useTranslation(["projects", "common"]);

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
        {!fixedTagIds && (
          <div className="w-full space-y-2 sm:w-48">
            <Label htmlFor="tag-filter" className="block font-medium text-muted-foreground text-xs">
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
          <Label htmlFor="project-sort" className="block font-medium text-muted-foreground text-xs">
            {t("filters.sortProjects")}
          </Label>
          <Select
            value={sortMode}
            onValueChange={(value) => onSortModeChange(value as ProjectSortMode)}
          >
            <SelectTrigger id="project-sort">
              <SelectValue placeholder={t("filters.selectSortOrder")} />
            </SelectTrigger>
            <SelectContent>
              {allowCustomSort ? (
                <SelectItem value="custom">{t("filters.sortCustom")}</SelectItem>
              ) : null}
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
          <div className="flex h-9 items-center gap-3 rounded-md border bg-background/60 px-3">
            <Switch
              id="favorites-only"
              checked={favoritesOnly}
              onCheckedChange={(checked) => onFavoritesOnlyChange(Boolean(checked))}
              aria-label={t("filters.showOnlyFavorites")}
            />
            <span className="text-muted-foreground text-sm">{t("filters.showOnlyFavorites")}</span>
          </div>
        </div>
      </div>
    </ToolFilterPanel>
  );
};
