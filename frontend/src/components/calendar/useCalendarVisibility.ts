import { useEffect, useMemo, useState } from "react";

import { getItem, setItem } from "@/lib/storage";

type Id = number | null | undefined;

// Keyed by community as well: the cross-community calendar holds several communities'
// calendars and projects, and their ids collide.
const keyOf = (communityId: Id, id: number): string => `${communityId ?? 0}:${id}`;

const readHidden = (storageKey: string) => {
  try {
    const parsed = JSON.parse(getItem(storageKey) ?? "null");
    return {
      calendars: new Set<string>(
        Array.isArray(parsed?.hiddenCalendarKeys) ? parsed.hiddenCalendarKeys : []
      ),
      projects: new Set<string>(
        Array.isArray(parsed?.hiddenProjectKeys) ? parsed.hiddenProjectKeys : []
      ),
      tasksHidden: parsed?.hideTasks === true,
    };
  } catch {
    return { calendars: new Set<string>(), projects: new Set<string>(), tasksHidden: false };
  }
};

const withKey = (prev: ReadonlySet<string>, key: string, hidden: boolean): Set<string> => {
  const next = new Set(prev);
  if (hidden) {
    next.add(key);
  } else {
    next.delete(key);
  }
  return next;
};

/** The stored keys of `communityId`'s calendars or projects. */
const communityKeys = (keys: ReadonlySet<string>, communityId: Id): string[] => {
  const prefix = keyOf(communityId, 0).slice(0, -1);
  return [...keys].filter((key) => key.startsWith(prefix));
};

/**
 * Which calendars, and which projects' task calendars, the reader has switched
 * off, kept under `storageKey`. Stored as the hidden sets so a calendar or
 * project that turns up later is shown. Tasks as a whole switch off on their
 * own, leaving the per-project choices as they were for when they come back.
 */
export const useCalendarVisibility = (storageKey: string) => {
  const [state, setState] = useState(() => ({ storageKey, ...readHidden(storageKey) }));
  let current = state;
  if (state.storageKey !== storageKey) {
    current = { storageKey, ...readHidden(storageKey) };
    setState(current);
  }

  useEffect(() => {
    setItem(
      current.storageKey,
      JSON.stringify({
        hiddenCalendarKeys: [...current.calendars],
        hiddenProjectKeys: [...current.projects],
        hideTasks: current.tasksHidden,
      })
    );
  }, [current]);

  // Stable across renders: they only write through the state setter.
  const actions = useMemo(
    () => ({
      toggleCalendar: (communityId: Id, calendarId: number) => {
        const key = keyOf(communityId, calendarId);
        setState((prev) => ({
          ...prev,
          calendars: withKey(prev.calendars, key, !prev.calendars.has(key)),
        }));
      },
      toggleProject: (communityId: Id, projectId: number) => {
        const key = keyOf(communityId, projectId);
        setState((prev) => ({
          ...prev,
          projects: withKey(prev.projects, key, !prev.projects.has(key)),
        }));
      },
      showCalendar: (communityId: Id, calendarId: number) => {
        const key = keyOf(communityId, calendarId);
        setState((prev) =>
          prev.calendars.has(key)
            ? { ...prev, calendars: withKey(prev.calendars, key, false) }
            : prev
        );
      },
      toggleTasks: () => setState((prev) => ({ ...prev, tasksHidden: !prev.tasksHidden })),
      /** Every calendar of `communityId` back on, loaded on this page or not. */
      showAllCalendars: (communityId: Id) =>
        setState((prev) => {
          const keys = communityKeys(prev.calendars, communityId);
          if (keys.length === 0) return prev;
          const calendars = new Set(prev.calendars);
          for (const key of keys) calendars.delete(key);
          return { ...prev, calendars };
        }),
      /** Tasks back on, every project's with them. */
      showTasks: () => setState((prev) => ({ ...prev, projects: new Set(), tasksHidden: false })),
      clear: () =>
        setState((prev) => ({
          ...prev,
          calendars: new Set(),
          projects: new Set(),
          tasksHidden: false,
        })),
    }),
    []
  );

  return useMemo(
    () => ({
      ...actions,
      isCalendarHidden: (communityId: Id, calendarId: number) =>
        current.calendars.has(keyOf(communityId, calendarId)),
      isProjectHidden: (communityId: Id, projectId: number) =>
        current.projects.has(keyOf(communityId, projectId)),
      /** Every calendar switched off in `communityId`, loaded on this page or not. */
      hiddenCalendarIds: (communityId: Id): number[] => {
        const prefix = keyOf(communityId, 0).slice(0, -1);
        return communityKeys(current.calendars, communityId).map((key) =>
          Number(key.slice(prefix.length))
        );
      },
      tasksHidden: current.tasksHidden,
      /** How far the tasks are narrowed: all of them off counts once, and
       *  makes the per-project choices moot. */
      hiddenTaskCount: current.tasksHidden ? 1 : current.projects.size,
      hiddenCount: current.calendars.size + current.projects.size + (current.tasksHidden ? 1 : 0),
    }),
    [actions, current]
  );
};
