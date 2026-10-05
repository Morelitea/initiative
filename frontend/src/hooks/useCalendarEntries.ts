import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  getListCalendarEntriesQueryKey,
  getListMyCalendarEntriesQueryKey,
  listCalendarEntries,
  listMyCalendarEntries,
} from "@/api/generated/calendar-entries/calendar-entries";
import type {
  CalendarEntriesResponse,
  ListCalendarEntriesParams,
  ListMyCalendarEntriesParams,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { QueryOpts } from "@/types/query";

/**
 * One request for a community calendar's events + task markers over a window.
 * Replaces the paired `useCalendarEventsList` + `useTasks` calls the Events
 * page used to fire; the client still merges the union into calendar entries.
 */
export const useCalendarEntries = (
  params: ListCalendarEntriesParams,
  options?: QueryOpts<CalendarEntriesResponse>
) => {
  const communityId = useActiveCommunityId();
  return useQuery<CalendarEntriesResponse>({
    queryKey: getListCalendarEntriesQueryKey(communityId, params),
    queryFn: () => listCalendarEntries(communityId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * Cross-community variant for the My Calendar page — the user's assigned task
 * markers + events across every community they belong to, in one request.
 */
export const useMyCalendarEntries = (
  params: ListMyCalendarEntriesParams,
  options?: QueryOpts<CalendarEntriesResponse>
) => {
  return useQuery<CalendarEntriesResponse>({
    queryKey: getListMyCalendarEntriesQueryKey(params),
    queryFn: () => listMyCalendarEntries(params),
    placeholderData: keepPreviousData,
    ...options,
  });
};
