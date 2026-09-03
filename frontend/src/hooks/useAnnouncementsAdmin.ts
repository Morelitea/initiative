import { useQuery } from "@tanstack/react-query";

import {
  createAnnouncementApiV1AnnouncementsAdminPost,
  deleteAnnouncementApiV1AnnouncementsAdminAnnouncementIdDelete,
  getListAllAnnouncementsApiV1AnnouncementsAdminGetQueryKey,
  listAllAnnouncementsApiV1AnnouncementsAdminGet,
  updateAnnouncementApiV1AnnouncementsAdminAnnouncementIdPatch,
  uploadAnnouncementImageApiV1AnnouncementsAdminImagesPost,
} from "@/api/generated/announcements/announcements";
import type {
  AnnouncementAdminListResponse,
  AnnouncementAdminRead,
  AnnouncementImageRead,
  AnnouncementUpdate,
  AnnouncementWrite,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAnnouncements } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { QueryOpts } from "@/types/query";

/** Every announcement, drafts and compiled-in notices included. */
export const usePlatformAnnouncements = (options?: QueryOpts<AnnouncementAdminListResponse>) =>
  useQuery<AnnouncementAdminListResponse>({
    queryKey: getListAllAnnouncementsApiV1AnnouncementsAdminGetQueryKey(),
    queryFn: () => listAllAnnouncementsApiV1AnnouncementsAdminGet(),
    ...options,
  });

export const useCreateAnnouncement = () =>
  useApiMutation<AnnouncementAdminRead, AnnouncementWrite>({
    mutationFn: (data) => createAnnouncementApiV1AnnouncementsAdminPost(data),
    invalidate: invalidateAnnouncements,
  });

export const useUpdateAnnouncement = () =>
  useApiMutation<AnnouncementAdminRead, { id: number; data: AnnouncementUpdate }>({
    mutationFn: ({ id, data }) =>
      updateAnnouncementApiV1AnnouncementsAdminAnnouncementIdPatch(id, data),
    invalidate: invalidateAnnouncements,
  });

export const useDeleteAnnouncement = () =>
  useApiMutation<void, number>({
    mutationFn: (id) => deleteAnnouncementApiV1AnnouncementsAdminAnnouncementIdDelete(id),
    invalidate: invalidateAnnouncements,
  });

/** Store one picture and get back the URL a section should point at. */
export const useUploadAnnouncementImage = () =>
  useApiMutation<AnnouncementImageRead, File>({
    mutationFn: (file) => uploadAnnouncementImageApiV1AnnouncementsAdminImagesPost({ file }),
  });
