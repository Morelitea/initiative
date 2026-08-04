import { keepPreviousData, useQuery } from "@tanstack/react-query";

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
  setCalendarEventGrantsApiV1GGuildIdCalendarEventsEventIdGrantsPut,
  setDocumentsApiV1GGuildIdCalendarEventsEventIdDocumentsPut,
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
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendarEvents, invalidateCalendarEvent } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
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
    queryFn: () => listCalendarEventsApiV1GGuildIdCalendarEventsGet(guildId, params),
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
    queryFn: () => listMyCalendarEventsApiV1MeCalendarEventsGet(params),
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
    queryFn: () => readCalendarEventApiV1GGuildIdCalendarEventsEventIdGet(guildId, eventId!),
    enabled: eventId !== null && Number.isFinite(eventId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateEventAndList = (eventId: number) =>
  Promise.all([invalidateCalendarEvent(eventId), invalidateAllCalendarEvents()]);

export const useCreateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, CalendarEventCreate>
) =>
  useGuildMutation<CalendarEventRead, CalendarEventCreate>(
    {
      mutationFn: (guildId, data) =>
        createCalendarEventApiV1GGuildIdCalendarEventsPost(guildId, data),
      invalidate: () => invalidateAllCalendarEvents(),
      errorKey: "calendarEvents:error",
    },
    options
  );

export const useUpdateCalendarEvent = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventUpdate>
) =>
  useGuildMutation<CalendarEventRead, CalendarEventUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateCalendarEventApiV1GGuildIdCalendarEventsEventIdPatch(guildId, eventId, data),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendarEvents:error",
    },
    options
  );

/**
 * Update an event identified per-call (the event id travels in the mutation
 * variables) rather than bound at hook construction. Used by the calendar
 * drag-to-reschedule flow, where the target event isn't known until drop time.
 */
export const useRescheduleCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; data: CalendarEventUpdate }>
) =>
  useGuildMutation<CalendarEventRead, { eventId: number; data: CalendarEventUpdate }>(
    {
      mutationFn: (guildId, { eventId, data }) =>
        updateCalendarEventApiV1GGuildIdCalendarEventsEventIdPatch(guildId, eventId, data),
      invalidate: (_data, { eventId }) => invalidateEventAndList(eventId),
      errorKey: "calendarEvents:error",
    },
    options
  );

export const useDeleteCalendarEvent = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, eventId) =>
        deleteCalendarEventApiV1GGuildIdCalendarEventsEventIdDelete(guildId, eventId),
      invalidate: () => invalidateAllCalendarEvents(),
      errorKey: "calendarEvents:error",
    },
    options
  );

// ── Association Mutations ───────────────────────────────────────────────────

export const useSetEventAttendees = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, number[]>
) =>
  useGuildMutation<CalendarEventRead, number[]>(
    {
      mutationFn: (guildId, userIds) =>
        setAttendeesApiV1GGuildIdCalendarEventsEventIdAttendeesPut(guildId, eventId, userIds),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendarEvents:error",
    },
    options
  );

export const useUpdateEventRSVP = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventRSVPUpdate>
) =>
  useGuildMutation<CalendarEventRead, CalendarEventRSVPUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateRsvpApiV1GGuildIdCalendarEventsEventIdRsvpPatch(guildId, eventId, data),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendarEvents:error",
    },
    options
  );

export const useSetEventDocuments = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, number[]>
) =>
  useGuildMutation<CalendarEventRead, number[]>(
    {
      mutationFn: (guildId, documentIds) =>
        setDocumentsApiV1GGuildIdCalendarEventsEventIdDocumentsPut(guildId, eventId, documentIds),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendarEvents:error",
    },
    options
  );

// ── Grants Mutation (unified resource sharing) ──────────────────────────────

export const useSetCalendarEventGrants = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<CalendarEventRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setCalendarEventGrantsApiV1GGuildIdCalendarEventsEventIdGrantsPut(guildId, eventId, grants),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendarEvents:error",
    },
    options
  );
