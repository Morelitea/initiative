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

/** What a board is showing: everything, or only what is still waiting. */
export type ReadFilter = "all" | "unread";

type PostsFilterBarProps = {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  readFilter: ReadFilter;
  onReadFilterChange: (value: ReadFilter) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets every filter this bar owns — offered in the mobile sheet. */
  onClear?: () => void;
};

/**
 * The board's filters, in the panel every other tool list uses.
 *
 * The board had a bare search box beside the toolbar, which is not what the
 * rest of the app does with filters — and it had nowhere to put a second one.
 */
export const PostsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  readFilter,
  onReadFilterChange,
  filtersOpen,
  onFiltersOpenChange,
  onClear,
  activeCount,
}: PostsFilterBarProps) => {
  const { t } = useTranslation(["posts", "common"]);

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
          {/* Not "by headline": this box is backed by the search index, which
              holds a notice's body as well as its title, so typing a word from
              the middle of a post finds it. */}
          <Label htmlFor="post-search" className="block font-medium text-muted-foreground text-xs">
            {t("filters.searchLabel")}
          </Label>
          <Input
            id="post-search"
            placeholder={t("filters.searchPosts")}
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            className="min-w-60"
          />
        </div>
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="post-read-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.readState")}
          </Label>
          <Select
            value={readFilter}
            onValueChange={(value) => onReadFilterChange(value as ReadFilter)}
          >
            <SelectTrigger id="post-read-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("filters.allPosts")}</SelectItem>
              <SelectItem value="unread">{t("filters.unreadOnly")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </ToolFilterPanel>
  );
};
