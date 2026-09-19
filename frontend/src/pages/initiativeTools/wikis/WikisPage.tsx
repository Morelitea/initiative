import { useRouter } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  archivedParam,
  ToolArchiveFilter,
  type ToolArchiveState,
} from "@/components/initiativeTools/shared/ToolArchiveFilter";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { CreateWikiDialog } from "@/components/initiativeTools/wikis/CreateWikiDialog";
import { WikiCard } from "@/components/initiativeTools/wikis/WikiCard";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { CardGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useWikisList } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

type WikisViewProps = {
  /** The initiative this list belongs to. Required: wikis are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's wikis, as cards.
 *
 * The list is the shelf; each wiki is its own body of pages. Search here reads
 * the index (name and description) — finding a page by what is written on it
 * happens inside the wiki, where the pages are.
 */
export const WikisView = ({ fixedInitiativeId, canCreate }: WikisViewProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilters, setTagFilters] = useState<TagSummary[]>([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(searchQuery, 300);

  // Which of the tool's two states the list is showing. Archived rows are
  // off the live list, so this is the only place they can be reached.
  const [archiveState, setArchiveState] = useState<ToolArchiveState>("active");

  const wikisQuery = useWikisList({
    initiative_id: fixedInitiativeId,
    archived: archivedParam(archiveState),
    ...(search.trim() ? { search: search.trim() } : {}),
    ...(tagFilters.length > 0 ? { tag_ids: tagFilters.map((tag) => tag.id) } : {}),
  });

  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.wiki, {
    initiativeId: fixedInitiativeId,
  });
  const canCreateWikis = canCreate ?? canCreateDerived;

  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam();

  useRegisterPrimaryCreateAction(
    canCreateWikis ? { run: () => setCreateDialogOpen(true), label: t("createWiki") } : null
  );

  const wikis = useMemo(() => wikisQuery.data?.items ?? [], [wikisQuery.data]);
  const activeFilterCount = (search.trim() ? 1 : 0) + (tagFilters.length > 0 ? 1 : 0);
  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setTagFilters([]);
  }, []);

  return (
    <div className="space-y-6">
      <ToolListToolbar
        leading={
          <ToolArchiveFilter tool={Tool.wiki} value={archiveState} onChange={setArchiveState} />
        }
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        actions={
          canCreateWikis ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="h-4 w-4" />
              {t("createWiki")}
            </Button>
          ) : null
        }
      />

      <ToolFilterPanel
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        title={t("filters.heading")}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      >
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-full space-y-2 lg:max-w-md lg:flex-1">
            <Label
              htmlFor="wiki-search"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("filters.searchLabel")}
            </Label>
            <Input
              id="wiki-search"
              placeholder={t("filters.searchWikis")}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
          <div className="w-full space-y-2 sm:w-64">
            <Label htmlFor="wiki-tags" className="block font-medium text-muted-foreground text-xs">
              {t("filters.tags")}
            </Label>
            <TagPicker
              id="wiki-tags"
              variant="filter"
              selectedTags={tagFilters}
              onChange={setTagFilters}
              placeholder={t("filters.anyTag")}
            />
          </div>
        </div>
      </ToolFilterPanel>

      {wikisQuery.isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <CardGridSkeleton />
        </SkeletonRegion>
      ) : wikisQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : wikis.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {wikis.map((wiki) => (
            <WikiCard key={wiki.id} wiki={wiki} />
          ))}
        </div>
      ) : activeFilterCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingWikis")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noWikis")}</CardTitle>
            <CardDescription>{t("noWikisDescription")}</CardDescription>
          </CardHeader>
          {canCreateWikis && (
            <CardContent>
              <Button onClick={() => setCreateDialogOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("createFirst")}
              </Button>
            </CardContent>
          )}
        </Card>
      )}

      <CreateWikiDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        initiativeId={fixedInitiativeId}
        onSuccess={(wiki) => {
          void router.navigate({
            to: gp(toolDetailRoute(Tool.wiki, fixedInitiativeId, wiki.id)),
          });
        }}
      />
    </div>
  );
};
