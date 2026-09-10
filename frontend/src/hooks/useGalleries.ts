import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  bulkDeleteGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesBulkDeletePost,
  createGalleryApiV1GGuildIdGalleriesPost,
  deleteGalleryApiV1GGuildIdGalleriesGalleryIdDelete,
  deleteGalleryImageApiV1GGuildIdGalleriesGalleryIdImagesImageIdDelete,
  deleteGalleryImageVersionApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsVersionIdDelete,
  getGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGet,
  getGalleryImageTimelineApiV1GGuildIdGalleriesGalleryIdImagesTimelineGet,
  getGetGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGetQueryKey,
  getGetGalleryImageTimelineApiV1GGuildIdGalleriesGalleryIdImagesTimelineGetQueryKey,
  getListGalleriesApiV1GGuildIdGalleriesGetQueryKey,
  getListGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesGetQueryKey,
  getListGalleryImageVersionsApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsGetQueryKey,
  getReadGalleryApiV1GGuildIdGalleriesGalleryIdGetQueryKey,
  listGalleriesApiV1GGuildIdGalleriesGet,
  listGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesGet,
  listGalleryImageVersionsApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsGet,
  readGalleryApiV1GGuildIdGalleriesGalleryIdGet,
  setGalleryGrantsApiV1GGuildIdGalleriesGalleryIdGrantsPut,
  updateGalleryApiV1GGuildIdGalleriesGalleryIdPatch,
  updateGalleryImageApiV1GGuildIdGalleriesGalleryIdImagesImageIdPatch,
  uploadGalleryImageApiV1GGuildIdGalleriesGalleryIdImagesPost,
  uploadGalleryImageVersionApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsPost,
} from "@/api/generated/galleries/galleries";
import type {
  GalleryCreate,
  GalleryImageBulkDelete,
  GalleryImageBulkDeleteResponse,
  GalleryImageListResponse,
  GalleryImageRead,
  GalleryImageUpdate,
  GalleryImageVersionRead,
  GalleryListResponse,
  GalleryRead,
  GalleryUpdate,
  GetGalleryImageTimelineApiV1GGuildIdGalleriesGalleryIdImagesTimelineGetParams,
  InitiativeGroupedCountsResponse,
  ListGalleriesApiV1GGuildIdGalleriesGetParams,
  ListGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesGetParams,
  ResourceGrantSchema,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Visible-gallery counts per initiative, for the sidebar badges. */
export const useGalleryCountsByInitiative = (
  options?: QueryOpts<InitiativeGroupedCountsResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey:
      getGetGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGetQueryKey(guildId),
    queryFn: () => getGalleryCountsByInitiativeApiV1GGuildIdGalleriesCountsByInitiativeGet(guildId),
    ...options,
  });
};

export const useGalleriesList = (
  params?: ListGalleriesApiV1GGuildIdGalleriesGetParams,
  options?: QueryOpts<GalleryListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<GalleryListResponse>({
    queryKey: getListGalleriesApiV1GGuildIdGalleriesGetQueryKey(guildId, params),
    queryFn: () => listGalleriesApiV1GGuildIdGalleriesGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useGallery = (galleryId: number | null, options?: QueryOpts<GalleryRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<GalleryRead>({
    queryKey: getReadGalleryApiV1GGuildIdGalleriesGalleryIdGetQueryKey(guildId, galleryId!),
    queryFn: () => readGalleryApiV1GGuildIdGalleriesGalleryIdGet(guildId, galleryId!),
    enabled: galleryId !== null && Number.isFinite(galleryId) && userEnabled,
    ...rest,
  });
};

/** The filters a gallery's picture list takes, without the page. */
export type GalleryImagesParams = Omit<
  ListGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesGetParams,
  "page"
>;

/**
 * A gallery's pictures, page by page, as somebody scrolls the wall.
 *
 * An infinite query rather than a page in the URL: a wall is scrolled, not
 * paged through, and what a page bounds is how much is fetched ahead of the
 * reader. `keepPreviousData` keeps the wall on screen while a changed filter
 * loads rather than blanking it.
 */
export const useGalleryImagesFeed = (galleryId: number | null, params?: GalleryImagesParams) => {
  const guildId = useActiveGuildId();
  return useInfiniteQuery({
    queryKey: getListGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesGetQueryKey(
      guildId,
      galleryId!,
      params
    ),
    queryFn: ({ pageParam }) =>
      listGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesGet(guildId, galleryId!, {
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
  params?: GetGalleryImageTimelineApiV1GGuildIdGalleriesGalleryIdImagesTimelineGetParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TimelineResponse>({
    queryKey: getGetGalleryImageTimelineApiV1GGuildIdGalleriesGalleryIdImagesTimelineGetQueryKey(
      guildId,
      galleryId!,
      params
    ),
    queryFn: () =>
      getGalleryImageTimelineApiV1GGuildIdGalleriesGalleryIdImagesTimelineGet(
        guildId,
        galleryId!,
        params
      ),
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
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<GalleryImageVersionRead[]>({
    queryKey:
      getListGalleryImageVersionsApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsGetQueryKey(
        guildId,
        galleryId,
        imageId!
      ),
    queryFn: () =>
      listGalleryImageVersionsApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsGet(
        guildId,
        galleryId,
        imageId!
      ),
    enabled: imageId !== null && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateGalleryAndList = (galleryId: number) =>
  invalidate(q.gallery(galleryId), q.allGalleries());

/** A picture changed, so the wall, the rail, and the gallery's own count and
 *  cover are all stale. */
const invalidateImages = (galleryId: number) =>
  invalidate(q.galleryImages(galleryId), q.gallery(galleryId), q.allGalleries());

export const useCreateGallery = (options?: MutationOpts<GalleryRead, GalleryCreate>) =>
  useGuildMutation<GalleryRead, GalleryCreate>(
    {
      mutationFn: (guildId, data) => createGalleryApiV1GGuildIdGalleriesPost(guildId, data),
      invalidate: () => invalidate(q.allGalleries()),
      errorKey: "galleries:error",
    },
    options
  );

export const useUpdateGallery = (
  galleryId: number,
  options?: MutationOpts<GalleryRead, GalleryUpdate>
) => {
  const guildId = useActiveGuildId();
  return useGuildMutation<GalleryRead, GalleryUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateGalleryApiV1GGuildIdGalleriesGalleryIdPatch(guildId, galleryId, data),
      invalidate: (updated) => {
        // The PATCH answers with the row a refetch would fetch, so seed it.
        queryClient.setQueryData(
          getReadGalleryApiV1GGuildIdGalleriesGalleryIdGetQueryKey(guildId, galleryId),
          updated
        );
        return invalidateGalleryAndList(galleryId);
      },
      errorKey: "galleries:error",
    },
    options
  );
};

export const useDeleteGallery = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, galleryId) =>
        deleteGalleryApiV1GGuildIdGalleriesGalleryIdDelete(guildId, galleryId),
      invalidate: () => invalidate(q.allGalleries()),
      errorKey: "galleries:error",
    },
    options
  );

export const useSetGalleryGrants = (
  galleryId: number,
  options?: MutationOpts<GalleryRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<GalleryRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setGalleryGrantsApiV1GGuildIdGalleriesGalleryIdGrantsPut(guildId, galleryId, grants),
      invalidate: () => invalidateGalleryAndList(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

// ── Pictures ────────────────────────────────────────────────────────────────

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
  useGuildMutation<GalleryImageRead, UploadGalleryImageVariables>(
    {
      mutationFn: (guildId, { file, title, caption }) =>
        uploadGalleryImageApiV1GGuildIdGalleriesGalleryIdImagesPost(guildId, galleryId, {
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
  useGuildMutation<GalleryImageRead, { imageId: number; data: GalleryImageUpdate }>(
    {
      mutationFn: (guildId, { imageId, data }) =>
        updateGalleryImageApiV1GGuildIdGalleriesGalleryIdImagesImageIdPatch(
          guildId,
          galleryId,
          imageId,
          data
        ),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

export const useDeleteGalleryImage = (galleryId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, imageId) =>
        deleteGalleryImageApiV1GGuildIdGalleriesGalleryIdImagesImageIdDelete(
          guildId,
          galleryId,
          imageId
        ),
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
  useGuildMutation<GalleryImageBulkDeleteResponse, number[]>(
    {
      mutationFn: (guildId, imageIds) =>
        bulkDeleteGalleryImagesApiV1GGuildIdGalleriesGalleryIdImagesBulkDeletePost(
          guildId,
          galleryId,
          { image_ids: imageIds } satisfies GalleryImageBulkDelete
        ),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

export const useUploadGalleryImageVersion = (
  galleryId: number,
  options?: MutationOpts<GalleryImageVersionRead, { imageId: number; file: File }>
) =>
  useGuildMutation<GalleryImageVersionRead, { imageId: number; file: File }>(
    {
      mutationFn: (guildId, { imageId, file }) =>
        uploadGalleryImageVersionApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsPost(
          guildId,
          galleryId,
          imageId,
          { file }
        ),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );

export const useDeleteGalleryImageVersion = (
  galleryId: number,
  options?: MutationOpts<void, { imageId: number; versionId: number }>
) =>
  useGuildMutation<void, { imageId: number; versionId: number }>(
    {
      mutationFn: (guildId, { imageId, versionId }) =>
        deleteGalleryImageVersionApiV1GGuildIdGalleriesGalleryIdImagesImageIdVersionsVersionIdDelete(
          guildId,
          galleryId,
          imageId,
          versionId
        ),
      invalidate: () => invalidateImages(galleryId),
      errorKey: "galleries:error",
    },
    options
  );
