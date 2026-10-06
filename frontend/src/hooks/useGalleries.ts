import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  bulkDeleteGalleryImages,
  deleteGalleryImage,
  deleteGalleryImageVersion,
  getGalleryImageTimeline,
  getGetGalleryImageTimelineQueryKey,
  getListGalleryImagesQueryKey,
  getListGalleryImageVersionsQueryKey,
  listGalleryImages,
  listGalleryImageVersions,
  updateGalleryImage,
  uploadGalleryImage,
  uploadGalleryImageVersion,
} from "@/api/generated/galleries/galleries";
import type {
  GalleryImageBulkDelete,
  GalleryImageBulkDeleteResponse,
  GalleryImageListResponse,
  GalleryImageRead,
  GalleryImageUpdate,
  GalleryImageVersionRead,
  GetGalleryImageTimelineParams,
  ListGalleryImagesParams,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const galleries = TOOL_HOOKS[Tool.gallery];
export const useGalleriesList = galleries.useList;
export const useGallery = galleries.useDetail;
export const useUpdateGallery = galleries.useUpdate;
export const useDeleteGallery = galleries.useDelete;
export const useSetGalleryGrants = galleries.useSetGrants;

// ── Pictures ────────────────────────────────────────────────────────────────

/** The filters a gallery's picture list takes, without the page. */
export type GalleryImagesParams = Omit<ListGalleryImagesParams, "page">;

/**
 * A gallery's pictures, page by page, as somebody scrolls the wall.
 *
 * An infinite query rather than a page in the URL: a wall is scrolled, not
 * paged through, and what a page bounds is how much is fetched ahead of the
 * reader. `keepPreviousData` keeps the wall on screen while a changed filter
 * loads rather than blanking it.
 */
export const useGalleryImagesFeed = (galleryId: number | null, params?: GalleryImagesParams) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    queryKey: getListGalleryImagesQueryKey(communityId, galleryId!, params),
    queryFn: ({ pageParam }) =>
      listGalleryImages(communityId, galleryId!, {
        ...params,
        page: pageParam as number,
      }),
    initialPageParam: 1,
    getNextPageParam: (last: GalleryImageListResponse) =>
      last.has_next ? last.page + 1 : undefined,
    placeholderData: keepPreviousData,
    enabled: galleryId !== null && Number.isFinite(galleryId),
  });
};

/**
 * The months a gallery has pictures in — what the timeline rail is drawn from.
 * Takes the same filters the feed does, so the rail is a picture of the feed
 * as it currently stands.
 */
export const useGalleryImagesTimeline = (
  galleryId: number | null,
  params?: GetGalleryImageTimelineParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TimelineResponse>({
    queryKey: getGetGalleryImageTimelineQueryKey(communityId, galleryId!, params),
    queryFn: () => getGalleryImageTimeline(communityId, galleryId!, params),
    enabled: galleryId !== null && Number.isFinite(galleryId) && userEnabled,
    ...rest,
  });
};

/** Every stored rendition of one picture. Fetched when somebody opens the
 *  picture's details — a wall of forty must not fetch forty histories. */
export const useGalleryImageVersions = (
  galleryId: number,
  imageId: number | null,
  options?: QueryOpts<GalleryImageVersionRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<GalleryImageVersionRead[]>({
    queryKey: getListGalleryImageVersionsQueryKey(communityId, galleryId, imageId!),
    queryFn: () => listGalleryImageVersions(communityId, galleryId, imageId!),
    enabled: imageId !== null && userEnabled,
    ...rest,
  });
};

/** A picture changed, so the wall, the rail, and the gallery's own count and
 *  cover are all stale. */
export const invalidateImages = (galleryId: number) =>
  invalidate(q.toolSubtree(Tool.gallery, galleryId), q.allGalleries());

export interface UploadGalleryImageVariables {
  file: File;
  title?: string | null;
  caption?: string | null;
}

/**
 * Add one picture. One request per file — a drop of forty is forty of these,
 * run a few at a time by the uploader, so one failure does not take the rest
 * with it.
 *
 * Deliberately invalidates nothing and toasts nothing: the uploader that
 * drives it refreshes the wall a few times over a drop rather than once per
 * picture — forty refetches of the list in a minute is a rate limit — and
 * reports failures per file, where forty toasts would be forty toasts.
 */
export const useUploadGalleryImage = (
  galleryId: number,
  options?: MutationOpts<GalleryImageRead, UploadGalleryImageVariables>
) =>
  useCommunityMutation<GalleryImageRead, UploadGalleryImageVariables>(
    {
      mutationFn: (communityId, { file, title, caption }) =>
        uploadGalleryImage(communityId, galleryId, {
          file,
          title: title ?? null,
          caption: caption ?? null,
        }),
    },
    options
  );

export const useUpdateGalleryImage = (
  galleryId: number,
  options?: MutationOpts<GalleryImageRead, { imageId: number; data: GalleryImageUpdate }>
) =>
  useCommunityMutation<GalleryImageRead, { imageId: number; data: GalleryImageUpdate }>(
    {
      mutationFn: (communityId, { imageId, data }) =>
        updateGalleryImage(communityId, galleryId, imageId, data),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

export const useDeleteGalleryImage = (galleryId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, imageId) => deleteGalleryImage(communityId, galleryId, imageId),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

/**
 * Send a selection of pictures to the trash together.
 *
 * One request, not one per picture: forty deletes would be forty round trips
 * and forty chances to half-succeed, where the endpoint refuses the whole
 * selection if any id is not this gallery's own.
 */
export const useBulkDeleteGalleryImages = (
  galleryId: number,
  options?: MutationOpts<GalleryImageBulkDeleteResponse, number[]>
) =>
  useCommunityMutation<GalleryImageBulkDeleteResponse, number[]>(
    {
      mutationFn: (communityId, imageIds) =>
        bulkDeleteGalleryImages(communityId, galleryId, {
          image_ids: imageIds,
        } satisfies GalleryImageBulkDelete),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

export const useUploadGalleryImageVersion = (
  galleryId: number,
  options?: MutationOpts<GalleryImageVersionRead, { imageId: number; file: File }>
) =>
  useCommunityMutation<GalleryImageVersionRead, { imageId: number; file: File }>(
    {
      mutationFn: (communityId, { imageId, file }) =>
        uploadGalleryImageVersion(communityId, galleryId, imageId, { file }),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

export const useDeleteGalleryImageVersion = (
  galleryId: number,
  options?: MutationOpts<void, { imageId: number; versionId: number }>
) =>
  useCommunityMutation<void, { imageId: number; versionId: number }>(
    {
      mutationFn: (communityId, { imageId, versionId }) =>
        deleteGalleryImageVersion(communityId, galleryId, imageId, versionId),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );
