import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  createCalendarEventApiV1CalendarEventsPost,
  deleteCalendarEventApiV1CalendarEventsEventIdDelete,
  getListCalendarEventsApiV1CalendarEventsGetQueryKey,
  getListGlobalCalendarEventsApiV1CalendarEventsGlobalGetQueryKey,
  getReadCalendarEventApiV1CalendarEventsEventIdGetQueryKey,
  listCalendarEventsApiV1CalendarEventsGet,
  listGlobalCalendarEventsApiV1CalendarEventsGlobalGet,
  readCalendarEventApiV1CalendarEventsEventIdGet,
  setAttendeesApiV1CalendarEventsEventIdAttendeesPut,
  setDocumentsApiV1CalendarEventsEventIdDocumentsPut,
  setTagsApiV1CalendarEventsEventIdTagsPut,
  updateCalendarEventApiV1CalendarEventsEventIdPatch,
  updateRsvpApiV1CalendarEventsEventIdRsvpPatch,
} from "@/api/generated/calendar-events/calendar-events";
import type {
  CalendarEventCreate,
  CalendarEventListResponse,
  CalendarEventRead,
  CalendarEventRSVPUpdate,
  CalendarEventUpdate,
  ListCalendarEventsApiV1CalendarEventsGetParams,
  ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendarEvents, invalidateCalendarEvent } from "@/api/query-keys";
import { toast } from "@/lib/chesterToast";
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

/**
 * Update an event identified per-call (the event id travels in the mutation
 * variables) rather than bound at hook construction. Used by the calendar
 * drag-to-reschedule flow, where the target event isn't known until drop time.
 */
export const useRescheduleCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; data: CalendarEventUpdate }>
) => {
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ eventId, data }: { eventId: number; data: CalendarEventUpdate }) =>
      updateCalendarEventApiV1CalendarEventsEventIdPatch(
        eventId,
        data
      ) as unknown as Promise<CalendarEventRead>,
    onSuccess: (...args) => {
      void invalidateCalendarEvent(args[1].eventId);
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
