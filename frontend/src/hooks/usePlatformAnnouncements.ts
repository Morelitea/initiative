import { useQuery } from "@tanstack/react-query";

import {
  createAnnouncement,
  deleteAnnouncement,
  getListAllAnnouncementsQueryKey,
  listAllAnnouncements,
  updateAnnouncement,
  uploadAnnouncementImage,
} from "@/api/generated/announcements/announcements";
import type {
  AnnouncementImageRead,
  AnnouncementOperatorListResponse,
  AnnouncementOperatorRead,
  AnnouncementUpdate,
  AnnouncementWrite,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { QueryOpts } from "@/types/query";

/** Every announcement, drafts and compiled-in notices included. */
export const usePlatformAnnouncements = (options?: QueryOpts<AnnouncementOperatorListResponse>) =>
  useQuery<AnnouncementOperatorListResponse>({
    queryKey: getListAllAnnouncementsQueryKey(),
    queryFn: () => listAllAnnouncements(),
    ...options,
  });

export const useCreateAnnouncement = () =>
  useApiMutation<AnnouncementOperatorRead, AnnouncementWrite>({
    mutationFn: (data) => createAnnouncement(data),
    invalidate: () => invalidate(q.announcements()),
  });

export const useUpdateAnnouncement = () =>
  useApiMutation<AnnouncementOperatorRead, { id: number; data: AnnouncementUpdate }>({
    mutationFn: ({ id, data }) => updateAnnouncement(id, data),
    invalidate: () => invalidate(q.announcements()),
  });

export const useDeleteAnnouncement = () =>
  useApiMutation<void, number>({
    mutationFn: (id) => deleteAnnouncement(id),
    invalidate: () => invalidate(q.announcements()),
  });

/** Store one picture and get back the URL a section should point at. */
export const useUploadAnnouncementImage = () =>
  useApiMutation<AnnouncementImageRead, File>({
    mutationFn: (file) => uploadAnnouncementImage({ file }),
  });
