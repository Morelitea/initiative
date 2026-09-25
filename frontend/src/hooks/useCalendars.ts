import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  CalendarListResponse,
  ListMyCalendarsApiV1MeCalendarsGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const calendars = TOOL_HOOKS[Tool.calendar];

export const useCalendarsList = calendars.useList;
export const useCalendar = calendars.useDetail;
export const useUpdateCalendar = calendars.useUpdate;
export const useDeleteCalendar = calendars.useDelete;
export const useSetCalendarGrants = calendars.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

/** Cross-guild variant for the My Calendar grouping panel — every calendar
 * visible to the user across their guilds, in one request. */
export const useMyCalendars = (
  params?: ListMyCalendarsApiV1MeCalendarsGetParams,
  options?: QueryOpts<CalendarListResponse>
) => {
  return useQuery<CalendarListResponse>({
    ...calendars.myListQuery(params),
    placeholderData: keepPreviousData,
    ...options,
  });
};
