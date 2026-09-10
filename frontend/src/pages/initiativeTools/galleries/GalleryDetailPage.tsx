import { Link, useParams } from "@tanstack/react-router";
import {
  Clock,
  Info,
  LayoutGrid,
  Loader2,
  Plus,
  SearchX,
  Settings,
  ShieldAlert,
  Tags,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  GalleryImageRead,
  TagSummary,
  TimelineBucket,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { BulkEditImageTagsDialog } from "@/components/initiativeTools/galleries/BulkEditImageTagsDialog";
import { GalleryBulkBar } from "@/components/initiativeTools/galleries/GalleryBulkBar";
import {
  GalleryDropzone,
  type GalleryDropzoneHandle,
} from "@/components/initiativeTools/galleries/GalleryDropzone";
import { GalleryGridView } from "@/components/initiativeTools/galleries/GalleryGridView";
import { GalleryImageSheet } from "@/components/initiativeTools/galleries/GalleryImageSheet";
import {
  GalleryImagesFilterBar,
  type ImageOrder,
} from "@/components/initiativeTools/galleries/GalleryImagesFilterBar";
import { GalleryMasonryView } from "@/components/initiativeTools/galleries/GalleryMasonryView";
import { GalleryTimelineView } from "@/components/initiativeTools/galleries/GalleryTimelineView";
import { MasonryIcon } from "@/components/initiativeTools/galleries/MasonryIcon";
import { UploadProgress } from "@/components/initiativeTools/galleries/UploadProgress";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { StatusMessage } from "@/components/StatusMessage";
import { Lightbox, type LightboxItem } from "@/components/shared/Lightbox";
import { CardGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { TagBadge } from "@/components/tags/TagBadge";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { RelativeTime } from "@/components/ui/relative-time";
import { Skeleton } from "@/components/ui/skeleton";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  useBulkDeleteGalleryImages,
  useGallery,
  useGalleryImagesFeed,
  useGalleryImagesTimeline,
  useUpdateGallery,
} from "@/hooks/useGalleries";
import { type GridToggleOptions, useGridSelection } from "@/hooks/useGridSelection";
import { useImageUploader } from "@/hooks/useImageUploader";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useViewPreference } from "@/hooks/useViewPreference";
import { toast } from "@/lib/chesterToast";
import { getHttpStatus } from "@/lib/errorMessage";
import { formatPeriod } from "@/lib/formatDate";
import { imageLabel, imageSrc } from "@/lib/galleries";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

type ViewMode = "masonry" | "grid" | "timeline";
const VIEW_KEY = "galleries:view-mode";
const GROUP_KEY = "galleries:group-by-tag";

const isViewMode = (value: unknown): value is ViewMode =>
  value === "masonry" || value === "grid" || value === "timeline";

/**
 * One gallery: the wall, and the ways of looking at it.
 *
 * Three views of one list. The masonry keeps every picture's shape and packs
 * them; the grid crops them to tiles so forty read at a glance; the timeline
 * is the gallery as a record, a row per day with a rail down the side for
 * jumping months. The first two can be grouped by tag, which is the one
 * grouping a design team asks for: "everything still awaiting a decision".
 *
 * The list is fetched a page at a time as the reader nears the bottom, and
 * every view keeps only the pictures near the viewport in the DOM — so a
 * gallery of a thousand costs a screen or two, however far it is scrolled.
 * The whole page is a drop target: pictures dragged in from a folder land
 * wherever the cursor is, which is over the wall.
 */
export function GalleryDetailPage() {
  const { t } = useTranslation(["galleries", "common"]);
  const { guildId, galleryId } = useParams({ strict: false }) as {
    guildId: string;
    galleryId: string;
  };
  const parsedId = Number(galleryId);
  const gp = useGuildPath();

  const galleryQuery = useGallery(Number.isFinite(parsedId) ? parsedId : null);
  const gallery = galleryQuery.data;
  const initiativeId = useCanonicalInitiativeId(gallery?.initiative_id);

  const recordViewMutation = useRecordRecentView("gallery", Number(guildId));
  const viewedId = gallery?.id;
  useEffect(() => {
    if (!viewedId) return;
    recordViewMutation.mutate(viewedId);
  }, [viewedId, recordViewMutation.mutate]);

  const canEdit = hasWriteAccess(gallery?.my_permission_level);
  const isOwner = gallery?.my_permission_level === "owner";

  // How the wall is looked at — remembered across galleries, because it is a
  // preference about walls rather than about this one.
  const [persistedView, setPersistedView] = useViewPreference<string>(VIEW_KEY, "masonry");
  const viewMode: ViewMode = isViewMode(persistedView) ? persistedView : "masonry";
  const [groupByTags, setGroupByTags] = useViewPreference<boolean>(GROUP_KEY, false);

  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilters, setTagFilters] = useState<TagSummary[]>([]);
  const [order, setOrder] = useState<ImageOrder>("newest");
  const changeOrder = useCallback((next: ImageOrder) => {
    setOrder(next);
    // An anchor names one end of a month, and which end is right depends on
    // the direction. Turning the list around releases the jump rather than
    // reading the anchor backwards.
    setAnchor(null);
  }, []);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(searchQuery, 300);

  // Where the timeline has been jumped to, if anywhere. Setting it re-anchors
  // the feed: a new query key, so the reader lands at that month rather than
  // paging through everything since.
  const [anchor, setAnchor] = useState<{ period: string; at: string } | null>(null);

  const filters = useMemo(
    () => ({
      ...(search.trim() ? { search: search.trim() } : {}),
      ...(tagFilters.length > 0 ? { tag_ids: tagFilters.map((tag) => tag.id) } : {}),
      ...(order === "oldest" ? { oldest_first: true } : {}),
    }),
    [search, tagFilters, order]
  );

  const feed = useGalleryImagesFeed(Number.isFinite(parsedId) ? parsedId : null, {
    ...filters,
    ...(anchor ? { until: anchor.at } : {}),
  });
  const images = useMemo(() => feed.data?.pages.flatMap((page) => page.items) ?? [], [feed.data]);
  const totalCount = feed.data?.pages[0]?.total_count ?? 0;
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = feed;

  // The rail is drawn WITHOUT the anchor: it is the map.
  const timelineQuery = useGalleryImagesTimeline(
    Number.isFinite(parsedId) ? parsedId : null,
    {
      ...(filters.search ? { search: filters.search } : {}),
      ...(filters.tag_ids ? { tag_ids: filters.tag_ids } : {}),
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    },
    { enabled: viewMode === "timeline" }
  );

  // The bottom of the wall asks for the next page as it comes into view.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "800px" }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  // Uploads.
  const uploader = useImageUploader(parsedId);
  const dropzoneRef = useRef<GalleryDropzoneHandle | null>(null);
  useRegisterPrimaryCreateAction(
    canEdit ? { run: () => dropzoneRef.current?.open(), label: t("addPictures") } : null
  );

  // The lightbox and the details panel. Both address a picture by id rather
  // than by index, so a page arriving underneath does not swap the picture
  // somebody is looking at.
  const [openId, setOpenId] = useState<number | null>(null);
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const openIndex = openId === null ? -1 : images.findIndex((image) => image.id === openId);
  const lightboxItems = useMemo<LightboxItem[]>(
    () =>
      images.map((image) => ({
        id: image.id,
        src: imageSrc(image),
        alt: imageLabel(image),
        caption: (
          <span className="inline-flex flex-wrap items-center justify-center gap-x-2">
            {imageLabel(image) ? <span>{imageLabel(image)}</span> : null}
            {image.uploader ? <UserHandle user={image.uploader} className="text-white/70" /> : null}
            <RelativeTime date={image.created_at} className="text-white/60" />
          </span>
        ),
      })),
    [images]
  );
  const onNearEnd = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const detailsImage = detailsId === null ? null : (images.find((i) => i.id === detailsId) ?? null);

  const setCover = useUpdateGallery(parsedId, {
    onSuccess: () => toast.success(t("sheet.coverSet")),
  });

  // Selecting pictures on the wall. The same click either opens a picture or
  // takes it into the selection, depending which the wall is doing — a tile is
  // the whole target, and a checkbox in the corner of a thumbnail is a
  // smaller one.
  const selection = useGridSelection(images);
  const selecting = selection.active;
  const selectedIds = selection.selectedIds;
  const isSelected = useCallback(
    (image: GalleryImageRead) => selectedIds.has(image.id),
    [selectedIds]
  );
  const onActivate = useCallback(
    (image: GalleryImageRead, options: GridToggleOptions) => {
      if (selection.active) selection.toggle(image, options);
      else setOpenId(image.id);
    },
    [selection.active, selection.toggle]
  );
  const selectAll = useCallback(() => {
    for (const image of images) {
      if (!selectedIds.has(image.id)) selection.toggle(image);
    }
  }, [images, selectedIds, selection.toggle]);

  const [bulkTagsOpen, setBulkTagsOpen] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const bulkDelete = useBulkDeleteGalleryImages(parsedId, {
    onSuccess: (result) => {
      setConfirmBulkDelete(false);
      selection.exit();
      // Anything removed cannot still be the picture the lightbox is showing.
      setOpenId(null);
      toast.success(t("bulk.deleted", { count: result.deleted_count }));
    },
  });
  const onJump = useCallback(
    (bucket: TimelineBucket) => {
      // Which end of the month to land on is the direction the list is read
      // in: newest first the page walks back from the month's last picture,
      // oldest first it walks forward from its first. Taking the wrong end
      // would jump to a month and show everything except it.
      setAnchor({
        period: bucket.period,
        at: order === "oldest" ? bucket.anchor_oldest : bucket.anchor,
      });
      document.querySelector<HTMLElement>("[data-app-scroll]")?.scrollTo({ top: 0 });
    },
    [order]
  );

  const activeFilterCount =
    (search.trim() ? 1 : 0) + (tagFilters.length > 0 ? 1 : 0) + (order === "oldest" ? 1 : 0);
  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setTagFilters([]);
    setOrder("newest");
    setAnchor(null);
  }, []);

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (galleryQuery.isError) {
    const status = getHttpStatus(galleryQuery.error);
    const backTo = gp(toolListRoute(Tool.gallery, initiativeId));
    const backLabel = t("backToGalleries");
    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("noAccess")}
          description={t("noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("notFound")}
        description={t("notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  const viewOptions = [
    { value: "masonry" as const, label: t("views.masonry"), icon: MasonryIcon },
    { value: "grid" as const, label: t("views.grid"), icon: LayoutGrid },
    { value: "timeline" as const, label: t("views.timeline"), icon: Clock },
  ];

  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={Tool.gallery}
        initiativeId={gallery?.initiative_id}
        trail={[{ label: gallery ? gallery.name : <Skeleton className="h-4 w-32" /> }]}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          {gallery ? (
            <h1 className="font-semibold text-3xl tracking-tight">{gallery.name}</h1>
          ) : (
            <Skeleton className="h-9 w-64" />
          )}
          {gallery?.description ? (
            <p className="max-w-prose text-muted-foreground">{gallery.description}</p>
          ) : null}
          {gallery && (
            <p className="text-muted-foreground text-sm">
              {t("pictureCount", { count: totalCount || gallery.image_count })}
            </p>
          )}
          {gallery && gallery.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {gallery.tags.map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {gallery && canEdit && (
            <Button variant="outline" size="sm" asChild>
              <Link
                to={gp(toolSettingsRoute(Tool.gallery, initiativeId, gallery.id))}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" aria-hidden />
                {t("common:toolSettings.title")}
              </Link>
            </Button>
          )}
        </div>
      </div>

      <ToolListToolbar
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        view={{
          value: viewMode,
          onChange: (value) => setPersistedView(value),
          options: viewOptions,
          label: t("views.label"),
        }}
        trailing={
          viewMode !== "timeline" ? (
            <Button
              // The same shape as the filter button beside it: outline when
              // off, secondary when on, label hidden on a narrow row.
              variant={groupByTags ? "secondary" : "outline"}
              size="sm"
              className="h-9 gap-2"
              aria-pressed={groupByTags}
              aria-label={t("groupByTag")}
              onClick={() => setGroupByTags(!groupByTags)}
            >
              <Tags className="h-4 w-4" />
              <span className="hidden sm:inline">{t("groupByTag")}</span>
            </Button>
          ) : null
        }
        onEnterSelection={canEdit && !selecting && images.length > 0 ? selection.enter : undefined}
        actions={
          canEdit ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => dropzoneRef.current?.open()}
            >
              <Plus className="h-4 w-4" />
              {t("addPictures")}
            </Button>
          ) : null
        }
      />

      <GalleryImagesFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        tags={tagFilters}
        onTagsChange={setTagFilters}
        order={order}
        onOrderChange={changeOrder}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      />

      {selecting && (
        <GalleryBulkBar
          count={selection.selectedItems.length}
          total={images.length}
          onSelectAll={selectAll}
          onClear={selection.clear}
          onEditTags={() => setBulkTagsOpen(true)}
          onDelete={() => setConfirmBulkDelete(true)}
          deleting={bulkDelete.isPending}
          onExit={selection.exit}
        />
      )}

      <UploadProgress
        jobs={uploader.jobs}
        total={uploader.total}
        done={uploader.done}
        failed={uploader.failed}
        active={uploader.active}
        onDismiss={uploader.dismiss}
      />

      {anchor && (
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-sm">
          <span>{t("common:timeline.jumpedTo", { period: formatPeriod(anchor.period) })}</span>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setAnchor(null)}>
            {t("common:timeline.backToLatest")}
          </Button>
        </div>
      )}

      <GalleryDropzone
        ref={dropzoneRef}
        enabled={canEdit}
        onFiles={uploader.enqueue}
        className="min-h-40 rounded-xl"
      >
        {feed.isLoading ? (
          <SkeletonRegion label={t("loadingPictures")}>
            <CardGridSkeleton
              count={8}
              className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
            />
          </SkeletonRegion>
        ) : feed.isError ? (
          <p className="text-destructive text-sm">{t("loadError")}</p>
        ) : images.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center">
            <p className="font-medium">
              {activeFilterCount > 0 ? t("filters.noMatchingPictures") : t("noPictures")}
            </p>
            {activeFilterCount === 0 && (
              <p className="max-w-md text-muted-foreground text-sm">
                {canEdit ? t("noPicturesDescription") : t("noPicturesReadOnly")}
              </p>
            )}
            {canEdit && activeFilterCount === 0 && (
              <Button onClick={() => dropzoneRef.current?.open()}>
                <Plus className="h-4 w-4" />
                {t("addPictures")}
              </Button>
            )}
          </div>
        ) : viewMode === "grid" ? (
          <GalleryGridView
            images={images}
            groupByTags={groupByTags}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
          />
        ) : viewMode === "timeline" ? (
          <GalleryTimelineView
            images={images}
            buckets={timelineQuery.data?.buckets ?? []}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
            onJump={onJump}
          />
        ) : (
          <GalleryMasonryView
            images={images}
            groupByTags={groupByTags}
            onActivate={onActivate}
            selecting={selecting}
            isSelected={isSelected}
          />
        )}
        <div ref={sentinelRef} className="h-px" />
        {isFetchingNextPage && (
          <div className="flex justify-center py-4">
            <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
          </div>
        )}
      </GalleryDropzone>

      {gallery != null && (
        <ToolCommentsPanel tool={Tool.gallery} entity={gallery} canModerate={canEdit} />
      )}

      <Lightbox
        open={openIndex >= 0}
        onOpenChange={(next) => {
          if (!next) setOpenId(null);
        }}
        items={lightboxItems}
        index={Math.max(openIndex, 0)}
        onIndexChange={(index) => setOpenId(images[index]?.id ?? null)}
        onNearEnd={onNearEnd}
        actions={
          openId !== null ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-white hover:bg-white/10 hover:text-white"
              onClick={() => setDetailsId(openId)}
            >
              <Info className="size-4" />
              {t("lightbox.details")}
            </Button>
          ) : null
        }
      />

      <BulkEditImageTagsDialog
        open={bulkTagsOpen}
        onOpenChange={setBulkTagsOpen}
        galleryId={parsedId}
        images={selection.selectedItems}
        onSuccess={selection.exit}
      />

      <ConfirmDialog
        open={confirmBulkDelete}
        onOpenChange={setConfirmBulkDelete}
        title={t("bulk.deleteTitle", { count: selection.selectedItems.length })}
        description={t("bulk.deleteDescription")}
        confirmLabel={t("bulk.delete")}
        cancelLabel={t("common:cancel")}
        isLoading={bulkDelete.isPending}
        destructive
        onConfirm={() => bulkDelete.mutate(selection.selectedItems.map((image) => image.id))}
      />

      <GalleryImageSheet
        galleryId={parsedId}
        image={detailsImage}
        open={detailsImage !== null}
        onOpenChange={(next) => {
          if (!next) setDetailsId(null);
        }}
        canEdit={canEdit}
        isOwner={isOwner}
        isCover={gallery?.cover_image_id === detailsId}
        onSetCover={(imageId) => setCover.mutate({ cover_image_id: imageId })}
        onRemoved={(imageId) => {
          if (openId === imageId) setOpenId(null);
        }}
      />
    </div>
  );
}
