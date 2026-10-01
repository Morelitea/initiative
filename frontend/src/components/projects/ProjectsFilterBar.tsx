import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolFilterFields, type ToolFilterFieldsProps } from "@/components/tools/ToolFilterFields";
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

type ProjectsFilterBarProps = ToolFilterFieldsProps<typeof Tool.project> & {
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  sortMode: ProjectSortMode;
  onSortModeChange: (value: ProjectSortMode) => void;
  favoritesOnly: boolean;
  onFavoritesOnlyChange: (value: boolean) => void;
  /** Manual ordering is only offered where the list can actually be dragged. */
  allowCustomSort?: boolean;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets search, tags, and favorites — offered in the mobile sheet. */
  onClear?: () => void;
};

/** The projects list's filters: the list's shared fields, then the reader's
 *  own sort order and favourites. */
export const ProjectsFilterBar = ({
  value,
  onChange,
  filtersOpen,
  onFiltersOpenChange,
  sortMode,
  onSortModeChange,
  favoritesOnly,
  onFavoritesOnlyChange,
  allowCustomSort = true,
  onClear,
  activeCount,
  initiativeId,
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
      <ToolFilterFields
        tool={Tool.project}
        value={value}
        onChange={onChange}
        initiativeId={initiativeId}
      >
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
      </ToolFilterFields>
    </ToolFilterPanel>
  );
};
