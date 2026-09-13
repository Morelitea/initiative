import { useRouter } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateGalleryDialog } from "@/components/initiativeTools/galleries/CreateGalleryDialog";
import { GalleryCard } from "@/components/initiativeTools/galleries/GalleryCard";
import {
  archivedParam,
  ToolArchiveFilter,
  type ToolArchiveState,
} from "@/components/initiativeTools/shared/ToolArchiveFilter";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { CardGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGalleriesList } from "@/hooks/useGalleries";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

type GalleriesViewProps = {
  /** The initiative this list belongs to. Required: galleries are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's galleries, as cards led by their covers.
 *
 * The list is the shelf; each gallery is its own wall. Search here reads the
 * index (name and description) — the filter box that finds a picture by its
 * caption is on the gallery's own page, where the pictures are.
 */
export const GalleriesView = ({ fixedInitiativeId, canCreate }: GalleriesViewProps) => {
  const { t } = useTranslation(["galleries", "common"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [searchQuery, setSearchQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(searchQuery, 300);

  // Which of the tool's two states the list is showing. Archived rows are
  // off the live list, so this is the only place they can be reached.
  const [archiveState, setArchiveState] = useState<ToolArchiveState>("active");

  const galleriesQuery = useGalleriesList({
    initiative_id: fixedInitiativeId,
    archived: archivedParam(archiveState),
    ...(search.trim() ? { search: search.trim() } : {}),
  });

  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.gallery, {
    initiativeId: fixedInitiativeId,
  });
  const canCreateGalleries = canCreate ?? canCreateDerived;

  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam();

  useRegisterPrimaryCreateAction(
    canCreateGalleries ? { run: () => setCreateDialogOpen(true), label: t("createGallery") } : null
  );

  const galleries = useMemo(() => galleriesQuery.data?.items ?? [], [galleriesQuery.data]);
  const activeFilterCount = search.trim() ? 1 : 0;
  const clearFilters = useCallback(() => setSearchQuery(""), []);

  return (
    <div className="space-y-6">
      <ToolListToolbar
        leading={
          <ToolArchiveFilter tool={Tool.gallery} value={archiveState} onChange={setArchiveState} />
        }
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        actions={
          canCreateGalleries ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="h-4 w-4" />
              {t("createGallery")}
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
        <div className="w-full space-y-2 lg:max-w-md">
          <Label
            htmlFor="gallery-search"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.searchLabel")}
          </Label>
          <Input
            id="gallery-search"
            placeholder={t("filters.searchGalleries")}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        </div>
      </ToolFilterPanel>

      {galleriesQuery.isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <CardGridSkeleton />
        </SkeletonRegion>
      ) : galleriesQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : galleries.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {galleries.map((gallery) => (
            <GalleryCard key={gallery.id} gallery={gallery} />
          ))}
        </div>
      ) : activeFilterCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingGalleries")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noGalleries")}</CardTitle>
            <CardDescription>{t("noGalleriesDescription")}</CardDescription>
          </CardHeader>
          {canCreateGalleries && (
            <CardContent>
              <Button onClick={() => setCreateDialogOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("createFirst")}
              </Button>
            </CardContent>
          )}
        </Card>
      )}

      <CreateGalleryDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        initiativeId={fixedInitiativeId}
        onSuccess={(gallery) => {
          void router.navigate({
            to: gp(toolDetailRoute(Tool.gallery, fixedInitiativeId, gallery.id)),
          });
        }}
      />
    </div>
  );
};
