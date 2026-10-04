import { useQuery } from "@tanstack/react-query";

import {
  addOccurrence,
  createCalendarEvent,
  deleteCalendarEvent,
  detachOccurrence,
  duplicateCalendarEvent,
  getReadCalendarEventQueryKey,
  importIcalEvents,
  openOccurrence,
  parseIcalFile,
  readCalendarEvent,
  restoreOccurrence,
  setAttendees,
  updateCalendarEvent,
  updateRsvp,
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
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
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
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const params = occurrence ? { occurrence } : undefined;
  return useQuery<CalendarEventRead>({
    queryKey: getReadCalendarEventQueryKey(communityId, eventId!, params),
    queryFn: () => readCalendarEvent(communityId, eventId!, params),
    enabled: eventId !== null && Number.isFinite(eventId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, CalendarEventCreate>
) =>
  useCommunityMutation<CalendarEventRead, CalendarEventCreate>(
    {
      mutationFn: (communityId, data) => createCalendarEvent(communityId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

export const useUpdateCalendarEvent = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventUpdate>
) =>
  useCommunityMutation<CalendarEventRead, CalendarEventUpdate>(
    {
      mutationFn: (communityId, data) => updateCalendarEvent(communityId, eventId, withZone(data)),
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
  useCommunityMutation<CalendarEventRead, { eventId: number; data: CalendarEventUpdate }>(
    {
      mutationFn: (communityId, { eventId, data }) =>
        updateCalendarEvent(communityId, eventId, withZone(data)),
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
  useCommunityMutation<void, { eventId: number } & OccurrenceTarget>(
    {
      mutationFn: (communityId, { eventId, ...target }) =>
        deleteCalendarEvent(communityId, eventId, target),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

/** Copies the event, or with `occurrence` that one date of a repeating event. */
export const useDuplicateCalendarEvent = (
  options?: MutationOpts<CalendarEventRead, { eventId: number; occurrence?: string }>
) =>
  useCommunityMutation<CalendarEventRead, { eventId: number; occurrence?: string }>(
    {
      mutationFn: (communityId, { eventId, occurrence }) =>
        duplicateCalendarEvent(communityId, eventId, {
          occurrence,
        }),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "common:error",
    },
    options
  );

// ── iCal Import ─────────────────────────────────────────────────────────────

/** Read an .ics file and report what is in it. Writes nothing. */
export const useParseIcalFile = (options?: MutationOpts<ICalParseResult, ICalParseRequest>) =>
  useCommunityMutation<ICalParseResult, ICalParseRequest>(
    {
      mutationFn: (communityId, data) => parseIcalFile(communityId, data),
      errorKey: "calendars:import.parseFailed",
    },
    options
  );

/** Create the file's events in one calendar. */
export const useImportIcalEvents = (options?: MutationOpts<ICalImportResult, ICalImportRequest>) =>
  useCommunityMutation<ICalImportResult, ICalImportRequest>(
    {
      mutationFn: (communityId, data) => importIcalEvents(communityId, data),
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
  useCommunityMutation<CalendarEventRead, { userIds: number[] } & OccurrenceTarget>(
    {
      mutationFn: (communityId, { userIds, ...target }) =>
        setAttendees(communityId, eventId, userIds, target),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

export const useUpdateEventRSVP = (
  eventId: number,
  options?: MutationOpts<CalendarEventRead, CalendarEventRSVPUpdate>
) =>
  useCommunityMutation<CalendarEventRead, CalendarEventRSVPUpdate>(
    {
      mutationFn: (communityId, data) => updateRsvp(communityId, eventId, data),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );

const OCCURRENCE_ACTIONS = {
  open: openOccurrence,
  detach: detachOccurrence,
  restore: restoreOccurrence,
  add: addOccurrence,
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
  useCommunityMutation<CalendarEventRead, string>(
    {
      mutationFn: (communityId, start) =>
        OCCURRENCE_ACTIONS[action](communityId, eventId, { start }),
      invalidate: () => invalidate(q.allCalendarEvents()),
      errorKey: "calendars:error",
    },
    options
  );
