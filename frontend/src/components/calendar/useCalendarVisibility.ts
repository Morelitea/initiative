import { useMemo } from "react";

import type { CalendarVisibility } from "@/lib/filters/calendarFilters";

type Id = number | null | undefined;

// Keyed by community as well: the cross-community calendar holds several communities'
// calendars and projects, and their ids collide.
const keyOf = (communityId: Id, id: number): string => `${communityId ?? 0}:${id}`;

const withKey = (prev: readonly string[], key: string, hidden: boolean): string[] => {
  const rest = prev.filter((each) => each !== key);
  return hidden ? [...rest, key] : rest;
};

/** The kept keys of `communityId`'s calendars or projects. */
const communityKeys = (keys: readonly string[], communityId: Id): string[] => {
  const prefix = keyOf(communityId, 0).slice(0, -1);
  return keys.filter((key) => key.startsWith(prefix));
};

/**
 * Which calendars, and which projects' task calendars, the reader has switched
 * off: part of their filters on a calendar page, kept with the rest of their
 * view. `change` takes what is hidden now and answers what is hidden next.
 * Tasks as a whole switch off on their own, leaving the per-project choices as
 * they were for when they come back.
 */
export const useCalendarVisibility = (
  visibility: CalendarVisibility,
  change: (next: (prev: CalendarVisibility) => CalendarVisibility) => void
) => {
  // Stable across renders: they only write through `change`.
  const actions = useMemo(
    () => ({
      toggleCalendar: (communityId: Id, calendarId: number) => {
        const key = keyOf(communityId, calendarId);
        change((prev) => ({
          ...prev,
          hiddenCalendarKeys: withKey(
            prev.hiddenCalendarKeys,
            key,
            !prev.hiddenCalendarKeys.includes(key)
          ),
        }));
      },
      toggleProject: (communityId: Id, projectId: number) => {
        const key = keyOf(communityId, projectId);
        change((prev) => ({
          ...prev,
          hiddenProjectKeys: withKey(
            prev.hiddenProjectKeys,
            key,
            !prev.hiddenProjectKeys.includes(key)
          ),
        }));
      },
      showCalendar: (communityId: Id, calendarId: number) => {
        const key = keyOf(communityId, calendarId);
        change((prev) =>
          prev.hiddenCalendarKeys.includes(key)
            ? { ...prev, hiddenCalendarKeys: withKey(prev.hiddenCalendarKeys, key, false) }
            : prev
        );
      },
      toggleTasks: () => change((prev) => ({ ...prev, hideTasks: !prev.hideTasks })),
      /** Every calendar of `communityId` back on, loaded on this page or not. */
      showAllCalendars: (communityId: Id) =>
        change((prev) => {
          const keys = communityKeys(prev.hiddenCalendarKeys, communityId);
          if (keys.length === 0) return prev;
          return {
            ...prev,
            hiddenCalendarKeys: prev.hiddenCalendarKeys.filter((key) => !keys.includes(key)),
          };
        }),
      /** Tasks back on, every project's with them. */
      showTasks: () => change((prev) => ({ ...prev, hiddenProjectKeys: [], hideTasks: false })),
      clear: () =>
        change((prev) => ({
          ...prev,
          hiddenCalendarKeys: [],
          hiddenProjectKeys: [],
          hideTasks: false,
        })),
    }),
    [change]
  );

  return useMemo(() => {
    const calendars = new Set(visibility.hiddenCalendarKeys);
    const projects = new Set(visibility.hiddenProjectKeys);
    return {
      ...actions,
      isCalendarHidden: (communityId: Id, calendarId: number) =>
        calendars.has(keyOf(communityId, calendarId)),
      isProjectHidden: (communityId: Id, projectId: number) =>
        projects.has(keyOf(communityId, projectId)),
      /** Every calendar switched off in `communityId`, loaded on this page or not. */
      hiddenCalendarIds: (communityId: Id): number[] => {
        const prefix = keyOf(communityId, 0).slice(0, -1);
        return communityKeys(visibility.hiddenCalendarKeys, communityId).map((key) =>
          Number(key.slice(prefix.length))
        );
      },
      tasksHidden: visibility.hideTasks,
      /** How far the tasks are narrowed: all of them off counts once, and
       *  makes the per-project choices moot. */
      hiddenTaskCount: visibility.hideTasks ? 1 : projects.size,
      hiddenCount: calendars.size + projects.size + (visibility.hideTasks ? 1 : 0),
    };
  }, [actions, visibility]);
};
