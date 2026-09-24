import { useQuery } from "@tanstack/react-query";

import {
  createCalendarEventApiV1CGuildIdCalendarEventsPost,
  deleteCalendarEventApiV1CGuildIdCalendarEventsEventIdDelete,
  getReadCalendarEventApiV1CGuildIdCalendarEventsEventIdGetQueryKey,
  importIcalEventsApiV1CGuildIdCalendarEventsImportPost,
  parseIcalFileApiV1CGuildIdCalendarEventsImportParsePost,
  readCalendarEventApiV1CGuildIdCalendarEventsEventIdGet,
  setAttendeesApiV1CGuildIdCalendarEventsEventIdAttendeesPut,
  setEventTagsApiV1CGuildIdCalendarEventsEventIdTagsPut,
  updateCalendarEventApiV1CGuildIdCalendarEventsEventIdPatch,
  updateRsvpApiV1CGuildIdCalendarEventsEventIdRsvpPatch,
} from "@/api/generated/calendar-events/calendar-events";
import type {
  CalendarEventCreate,
  CalendarEventRead,
  CalendarEventRSVPUpdate,
  CalendarEventUpdate,
  ICalImportRequest,
  ICalImportResult,
  ICalParseRequest,
  ICalParseResult,
  TagSetRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

export const useCalendarEvent = (
  eventId: number | null,
  options?: QueryOpts<CalendarEventRead>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<CalendarEventRead>({
    queryKey: getReadCalendarEventApiV1CGuildIdCalendarEventsEventIdGetQueryKey(guildId, eventId!),
    queryFn: () => readCalendarEventApiV1CGuildIdCalendarEventsEventIdGet(guildId, eventId!),
    enabled: eventId !== null && Number.isFinite(eventId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateEventAndList = (eventId: number) =>
  invalidate(q.calendarEvent(eventId), q.allCalendarEvents());

export const useCreateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, CalendarEventCreate>
) =>
  useGuildMutation<CalendarEventRead, CalendarEventCreate>(
    {
      mutationFn: (guildId, data) =>
        createCalendarEventApiV1CGuildIdCalendarEventsPost(guildId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
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
        updateCalendarEventApiV1CGuildIdCalendarEventsEventIdPatch(guildId, eventId, data),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendars:error",
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
        updateCalendarEventApiV1CGuildIdCalendarEventsEventIdPatch(guildId, eventId, data),
      invalidate: (_data, { eventId }) => invalidateEventAndList(eventId),
      errorKey: "calendars:error",
    },
    options
  );

export const useDeleteCalendarEvent = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, eventId) =>
        deleteCalendarEventApiV1CGuildIdCalendarEventsEventIdDelete(guildId, eventId),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

// ── iCal Import ─────────────────────────────────────────────────────────────

/** Read an .ics file and report what is in it. Writes nothing. */
export const useParseIcalFile = (options?: MutationOpts<ICalParseResult, ICalParseRequest>) =>
  useGuildMutation<ICalParseResult, ICalParseRequest>(
    {
      mutationFn: (guildId, data) =>
        parseIcalFileApiV1CGuildIdCalendarEventsImportParsePost(guildId, data),
      errorKey: "calendars:import.parseFailed",
    },
    options
  );

/** Create the file's events in one calendar. */
export const useImportIcalEvents = (options?: MutationOpts<ICalImportResult, ICalImportRequest>) =>
  useGuildMutation<ICalImportResult, ICalImportRequest>(
    {
      mutationFn: (guildId, data) =>
        importIcalEventsApiV1CGuildIdCalendarEventsImportPost(guildId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:import.importError",
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
        setAttendeesApiV1CGuildIdCalendarEventsEventIdAttendeesPut(guildId, eventId, userIds),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendars:error",
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
        updateRsvpApiV1CGuildIdCalendarEventsEventIdRsvpPatch(guildId, eventId, data),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendars:error",
    },
    options
  );

/** Events are content-level extras (like tasks), so tag assignment goes
 * through their own route, not the generic /tools one. */
export const useSetEventTags = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, TagSetRequest>
) =>
  useGuildMutation<CalendarEventRead, TagSetRequest>(
    {
      mutationFn: (guildId, data) =>
        setEventTagsApiV1CGuildIdCalendarEventsEventIdTagsPut(guildId, eventId, data),
      invalidate: () => invalidateEventAndList(eventId),
      errorKey: "calendars:error",
    },
    options
  );
