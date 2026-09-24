import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  getListCalendarEntriesApiV1CGuildIdCalendarEntriesGetQueryKey,
  getListMyCalendarEntriesApiV1MeCalendarEntriesGetQueryKey,
  listCalendarEntriesApiV1CGuildIdCalendarEntriesGet,
  listMyCalendarEntriesApiV1MeCalendarEntriesGet,
} from "@/api/generated/calendar-entries/calendar-entries";
import type {
  CalendarEntriesResponse,
  ListCalendarEntriesApiV1CGuildIdCalendarEntriesGetParams,
  ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { QueryOpts } from "@/types/query";

/**
 * One request for a guild calendar's events + task markers over a window.
 * Replaces the paired `useCalendarEventsList` + `useTasks` calls the Events
 * page used to fire; the client still merges the union into calendar entries.
 */
export const useCalendarEntries = (
  params: ListCalendarEntriesApiV1CGuildIdCalendarEntriesGetParams,
  options?: QueryOpts<CalendarEntriesResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<CalendarEntriesResponse>({
    queryKey: getListCalendarEntriesApiV1CGuildIdCalendarEntriesGetQueryKey(guildId, params),
    queryFn: () => listCalendarEntriesApiV1CGuildIdCalendarEntriesGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * Cross-guild variant for the My Calendar page — the user's assigned task
 * markers + events across every guild they belong to, in one request.
 */
export const useMyCalendarEntries = (
  params: ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams,
  options?: QueryOpts<CalendarEntriesResponse>
) => {
  return useQuery<CalendarEntriesResponse>({
    queryKey: getListMyCalendarEntriesApiV1MeCalendarEntriesGetQueryKey(params),
    queryFn: () => listMyCalendarEntriesApiV1MeCalendarEntriesGet(params),
    placeholderData: keepPreviousData,
    ...options,
  });
};
