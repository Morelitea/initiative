import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  createCalendarApiV1GGuildIdCalendarsPost,
  deleteCalendarApiV1GGuildIdCalendarsCalendarIdDelete,
  getCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGet,
  getGetCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGetQueryKey,
  getListCalendarsApiV1GGuildIdCalendarsGetQueryKey,
  getListMyCalendarsApiV1MeCalendarsGetQueryKey,
  getReadCalendarApiV1GGuildIdCalendarsCalendarIdGetQueryKey,
  listCalendarsApiV1GGuildIdCalendarsGet,
  listMyCalendarsApiV1MeCalendarsGet,
  readCalendarApiV1GGuildIdCalendarsCalendarIdGet,
  setCalendarGrantsApiV1GGuildIdCalendarsCalendarIdGrantsPut,
  updateCalendarApiV1GGuildIdCalendarsCalendarIdPatch,
} from "@/api/generated/calendars/calendars";
import type {
  CalendarCreate,
  CalendarListResponse,
  CalendarRead,
  CalendarUpdate,
  InitiativeGroupedCountsResponse,
  ListCalendarsApiV1GGuildIdCalendarsGetParams,
  ListMyCalendarsApiV1MeCalendarsGetParams,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendars, invalidateCalendar } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useCalendarsList = (
  params?: ListCalendarsApiV1GGuildIdCalendarsGetParams,
  options?: QueryOpts<CalendarListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<CalendarListResponse>({
    queryKey: getListCalendarsApiV1GGuildIdCalendarsGetQueryKey(guildId, params),
    queryFn: () => listCalendarsApiV1GGuildIdCalendarsGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/** Visible-calendar counts per initiative, for the sidebar badges. */
export const useCalendarCountsByInitiative = (
  options?: QueryOpts<InitiativeGroupedCountsResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey:
      getGetCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGetQueryKey(guildId),
    queryFn: () =>
      getCalendarCountsByInitiativeApiV1GGuildIdCalendarsCountsByInitiativeGet(guildId),
    ...options,
  });
};

/** Cross-guild variant for the My Calendar grouping panel — every calendar
 * visible to the user across their guilds, in one request. */
export const useMyCalendars = (
  params?: ListMyCalendarsApiV1MeCalendarsGetParams,
  options?: QueryOpts<CalendarListResponse>
) => {
  return useQuery<CalendarListResponse>({
    queryKey: getListMyCalendarsApiV1MeCalendarsGetQueryKey(params),
    queryFn: () => listMyCalendarsApiV1MeCalendarsGet(params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useCalendar = (calendarId: number | null, options?: QueryOpts<CalendarRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<CalendarRead>({
    queryKey: getReadCalendarApiV1GGuildIdCalendarsCalendarIdGetQueryKey(guildId, calendarId!),
    queryFn: () => readCalendarApiV1GGuildIdCalendarsCalendarIdGet(guildId, calendarId!),
    enabled: calendarId !== null && Number.isFinite(calendarId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateCalendarAndList = (calendarId: number) =>
  Promise.all([invalidateCalendar(calendarId), invalidateAllCalendars()]);

export const useCreateCalendar = (options?: MutationOpts<CalendarRead, CalendarCreate>) =>
  useGuildMutation<CalendarRead, CalendarCreate>(
    {
      mutationFn: (guildId, data) => createCalendarApiV1GGuildIdCalendarsPost(guildId, data),
      invalidate: () => invalidateAllCalendars(),
      errorKey: "calendars:error",
    },
    options
  );

export const useUpdateCalendar = (
  calendarId: number,
  options?: MutationOpts<CalendarRead, CalendarUpdate>
) =>
  useGuildMutation<CalendarRead, CalendarUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateCalendarApiV1GGuildIdCalendarsCalendarIdPatch(guildId, calendarId, data),
      invalidate: () => invalidateCalendarAndList(calendarId),
      errorKey: "calendars:error",
    },
    options
  );

export const useDeleteCalendar = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, calendarId) =>
        deleteCalendarApiV1GGuildIdCalendarsCalendarIdDelete(guildId, calendarId),
      invalidate: () => invalidateAllCalendars(),
      errorKey: "calendars:error",
    },
    options
  );

// ── Grants Mutation (unified resource sharing) ──────────────────────────────

export const useSetCalendarGrants = (
  calendarId: number,
  options?: MutationOpts<CalendarRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<CalendarRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setCalendarGrantsApiV1GGuildIdCalendarsCalendarIdGrantsPut(guildId, calendarId, grants),
      invalidate: () => invalidateCalendarAndList(calendarId),
      errorKey: "calendars:error",
    },
    options
  );
