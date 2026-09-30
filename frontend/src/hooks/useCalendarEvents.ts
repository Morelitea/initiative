import { useQuery } from "@tanstack/react-query";

import {
  addOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesAddPost,
  createCalendarEventApiV1CGuildIdCalendarEventsPost,
  deleteCalendarEventApiV1CGuildIdCalendarEventsEventIdDelete,
  detachOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesDetachPost,
  getReadCalendarEventApiV1CGuildIdCalendarEventsEventIdGetQueryKey,
  importIcalEventsApiV1CGuildIdCalendarEventsImportPost,
  openOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesPost,
  parseIcalFileApiV1CGuildIdCalendarEventsImportParsePost,
  readCalendarEventApiV1CGuildIdCalendarEventsEventIdGet,
  restoreOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesRestorePost,
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
  CalendarEventUpdateScope,
  ICalImportRequest,
  ICalImportResult,
  ICalParseRequest,
  ICalParseResult,
  TagSetRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { withZone } from "@/lib/recurrence";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/**
 * One event. `occurrence` names one occurrence of a repeating event, whose
 * attendees' answers are shown in place of the series'.
 */
export const useCalendarEvent = (
  eventId: number | null,
  options?: QueryOpts<CalendarEventRead>,
  occurrence?: string | null
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const params = occurrence ? { occurrence } : undefined;
  return useQuery<CalendarEventRead>({
    queryKey: getReadCalendarEventApiV1CGuildIdCalendarEventsEventIdGetQueryKey(
      guildId,
      eventId!,
      params
    ),
    queryFn: () =>
      readCalendarEventApiV1CGuildIdCalendarEventsEventIdGet(guildId, eventId!, params),
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
        updateCalendarEventApiV1CGuildIdCalendarEventsEventIdPatch(
          guildId,
          eventId,
          withZone(data)
        ),
      invalidate: () => invalidate(q.allCalendarEvents()),
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
        updateCalendarEventApiV1CGuildIdCalendarEventsEventIdPatch(
          guildId,
          eventId,
          withZone(data)
        ),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

/** Which occurrences of a repeating event a change is for, and the one named. */
export type OccurrenceTarget = {
  scope?: NonNullable<CalendarEventUpdateScope>;
  occurrence?: string;
};

export const useDeleteCalendarEvent = (
  options?: MutationOpts<void, { eventId: number } & OccurrenceTarget>
) =>
  useGuildMutation<void, { eventId: number } & OccurrenceTarget>(
    {
      mutationFn: (guildId, { eventId, ...target }) =>
        deleteCalendarEventApiV1CGuildIdCalendarEventsEventIdDelete(guildId, eventId, target),
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
  options?: MutationOpts<CalendarEventRead, { userIds: number[] } & OccurrenceTarget>
) =>
  useGuildMutation<CalendarEventRead, { userIds: number[] } & OccurrenceTarget>(
    {
      mutationFn: (guildId, { userIds, ...target }) =>
        setAttendeesApiV1CGuildIdCalendarEventsEventIdAttendeesPut(
          guildId,
          eventId,
          userIds,
          target
        ),
      invalidate: () => invalidate(q.allCalendarEvents()),
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
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

const OCCURRENCE_ACTIONS = {
  open: openOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesPost,
  detach: detachOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesDetachPost,
  restore: restoreOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesRestorePost,
  add: addOccurrenceApiV1CGuildIdCalendarEventsEventIdOccurrencesAddPost,
};

/**
 * One occurrence of a repeating event, by its start: `open` it as a row of
 * its own, `detach` it into an event of its own, `restore` it when skipped,
 * or `add` it as an extra start.
 */
export const useOccurrenceAction = (
  eventId: number,
  action: keyof typeof OCCURRENCE_ACTIONS,
  options?: MutationOpts<CalendarEventRead, string>
) =>
  useGuildMutation<CalendarEventRead, string>(
    {
      mutationFn: (guildId, start) => OCCURRENCE_ACTIONS[action](guildId, eventId, { start }),
      invalidate: () => invalidate(q.allCalendarEvents()),
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
