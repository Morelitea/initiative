import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listCalendarEventsApiV1CalendarEventsGet,
  getListCalendarEventsApiV1CalendarEventsGetQueryKey,
  listGlobalCalendarEventsApiV1CalendarEventsGlobalGet,
  getListGlobalCalendarEventsApiV1CalendarEventsGlobalGetQueryKey,
  readCalendarEventApiV1CalendarEventsEventIdGet,
  getReadCalendarEventApiV1CalendarEventsEventIdGetQueryKey,
  createCalendarEventApiV1CalendarEventsPost,
  updateCalendarEventApiV1CalendarEventsEventIdPatch,
  deleteCalendarEventApiV1CalendarEventsEventIdDelete,
  setAttendeesApiV1CalendarEventsEventIdAttendeesPut,
  updateRsvpApiV1CalendarEventsEventIdRsvpPatch,
  setTagsApiV1CalendarEventsEventIdTagsPut,
  setDocumentsApiV1CalendarEventsEventIdDocumentsPut,
} from "@/api/generated/calendar-events/calendar-events";
import { invalidateAllCalendarEvents, invalidateCalendarEvent } from "@/api/query-keys";
import type {
  ListCalendarEventsApiV1CalendarEventsGetParams,
  ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams,
  CalendarEventCreate,
  CalendarEventUpdate,
  CalendarEventRead,
  CalendarEventListResponse,
  CalendarEventRSVPUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useCalendarEventsList = (
  params: ListCalendarEventsApiV1CalendarEventsGetParams,
  options?: QueryOpts<CalendarEventListResponse>
) => {
  return useQuery<CalendarEventListResponse>({
    queryKey: getListCalendarEventsApiV1CalendarEventsGetQueryKey(params),
    queryFn: () =>
      listCalendarEventsApiV1CalendarEventsGet(
        params
      ) as unknown as Promise<CalendarEventListResponse>,
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useGlobalCalendarEventsList = (
  params: ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams,
  options?: QueryOpts<CalendarEventListResponse>
) => {
  return useQuery<CalendarEventListResponse>({
    queryKey: getListGlobalCalendarEventsApiV1CalendarEventsGlobalGetQueryKey(params),
    queryFn: () =>
      listGlobalCalendarEventsApiV1CalendarEventsGlobalGet(
        params
      ) as unknown as Promise<CalendarEventListResponse>,
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useCalendarEvent = (
  eventId: number | null,
  options?: QueryOpts<CalendarEventRead>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<CalendarEventRead>({
    queryKey: getReadCalendarEventApiV1CalendarEventsEventIdGetQueryKey(eventId!),
    queryFn: () =>
      readCalendarEventApiV1CalendarEventsEventIdGet(
        eventId!
      ) as unknown as Promise<CalendarEventRead>,
    enabled: eventId !== null && Number.isFinite(eventId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, CalendarEventCreate>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CalendarEventCreate) => {
      return createCalendarEventApiV1CalendarEventsPost(
        data
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateCalendarEvent = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventUpdate>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CalendarEventUpdate) => {
      return updateCalendarEventApiV1CalendarEventsEventIdPatch(
        eventId,
        data
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (...args) => {
      void invalidateCalendarEvent(eventId);
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteCalendarEvent = (options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (eventId: number) => {
      await deleteCalendarEventApiV1CalendarEventsEventIdDelete(eventId);
    },
    onSuccess: (...args) => {
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Association Mutations ───────────────────────────────────────────────────

export const useSetEventAttendees = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, number[]>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userIds: number[]) => {
      return setAttendeesApiV1CalendarEventsEventIdAttendeesPut(
        eventId,
        userIds
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (...args) => {
      void invalidateCalendarEvent(eventId);
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateEventRSVP = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventRSVPUpdate>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CalendarEventRSVPUpdate) => {
      return updateRsvpApiV1CalendarEventsEventIdRsvpPatch(
        eventId,
        data
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (...args) => {
      void invalidateCalendarEvent(eventId);
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetEventTags = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, number[]>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (tagIds: number[]) => {
      return setTagsApiV1CalendarEventsEventIdTagsPut(
        eventId,
        tagIds
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (...args) => {
      void invalidateCalendarEvent(eventId);
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetEventDocuments = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, number[]>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentIds: number[]) => {
      return setDocumentsApiV1CalendarEventsEventIdDocumentsPut(
        eventId,
        documentIds
      ) as unknown as Promise<CalendarEventRead>;
    },
    onSuccess: (...args) => {
      void invalidateCalendarEvent(eventId);
      void invalidateAllCalendarEvents();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};
