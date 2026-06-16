import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  createCalendarEventApiV1GGuildIdCalendarEventsPost,
  deleteCalendarEventApiV1GGuildIdCalendarEventsEventIdDelete,
  getListCalendarEventsApiV1GGuildIdCalendarEventsGetQueryKey,
  getListMyCalendarEventsApiV1MeCalendarEventsGetQueryKey,
  getReadCalendarEventApiV1GGuildIdCalendarEventsEventIdGetQueryKey,
  listCalendarEventsApiV1GGuildIdCalendarEventsGet,
  listMyCalendarEventsApiV1MeCalendarEventsGet,
  readCalendarEventApiV1GGuildIdCalendarEventsEventIdGet,
  setAttendeesApiV1GGuildIdCalendarEventsEventIdAttendeesPut,
  setDocumentsApiV1GGuildIdCalendarEventsEventIdDocumentsPut,
  setTagsApiV1GGuildIdCalendarEventsEventIdTagsPut,
  updateCalendarEventApiV1GGuildIdCalendarEventsEventIdPatch,
  updateRsvpApiV1GGuildIdCalendarEventsEventIdRsvpPatch,
} from "@/api/generated/calendar-events/calendar-events";
import type {
  CalendarEventCreate,
  CalendarEventListResponse,
  CalendarEventRead,
  CalendarEventRSVPUpdate,
  CalendarEventUpdate,
  ListCalendarEventsApiV1GGuildIdCalendarEventsGetParams,
  ListMyCalendarEventsApiV1MeCalendarEventsGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendarEvents, invalidateCalendarEvent } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useCalendarEventsList = (
  params: ListCalendarEventsApiV1GGuildIdCalendarEventsGetParams,
  options?: QueryOpts<CalendarEventListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<CalendarEventListResponse>({
    queryKey: getListCalendarEventsApiV1GGuildIdCalendarEventsGetQueryKey(guildId, params),
    queryFn: () =>
      listCalendarEventsApiV1GGuildIdCalendarEventsGet(
        guildId,
        params
      ) as unknown as Promise<CalendarEventListResponse>,
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useGlobalCalendarEventsList = (
  params: ListMyCalendarEventsApiV1MeCalendarEventsGetParams,
  options?: QueryOpts<CalendarEventListResponse>
) => {
  return useQuery<CalendarEventListResponse>({
    queryKey: getListMyCalendarEventsApiV1MeCalendarEventsGetQueryKey(params),
    queryFn: () =>
      listMyCalendarEventsApiV1MeCalendarEventsGet(
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
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<CalendarEventRead>({
    queryKey: getReadCalendarEventApiV1GGuildIdCalendarEventsEventIdGetQueryKey(guildId, eventId!),
    queryFn: () =>
      readCalendarEventApiV1GGuildIdCalendarEventsEventIdGet(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CalendarEventCreate) => {
      return createCalendarEventApiV1GGuildIdCalendarEventsPost(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CalendarEventUpdate) => {
      return updateCalendarEventApiV1GGuildIdCalendarEventsEventIdPatch(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ eventId, data }: { eventId: number; data: CalendarEventUpdate }) =>
      updateCalendarEventApiV1GGuildIdCalendarEventsEventIdPatch(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (eventId: number) => {
      await deleteCalendarEventApiV1GGuildIdCalendarEventsEventIdDelete(guildId, eventId);
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userIds: number[]) => {
      return setAttendeesApiV1GGuildIdCalendarEventsEventIdAttendeesPut(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CalendarEventRSVPUpdate) => {
      return updateRsvpApiV1GGuildIdCalendarEventsEventIdRsvpPatch(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (tagIds: number[]) => {
      return setTagsApiV1GGuildIdCalendarEventsEventIdTagsPut(
        guildId,
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
  const guildId = useActiveGuildId();
  const { t } = useTranslation("events");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentIds: number[]) => {
      return setDocumentsApiV1GGuildIdCalendarEventsEventIdDocumentsPut(
        guildId,
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
