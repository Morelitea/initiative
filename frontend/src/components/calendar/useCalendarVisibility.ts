import { useEffect, useMemo, useState } from "react";

import { getItem, setItem } from "@/lib/storage";

type Id = number | null | undefined;

// Keyed by guild as well: the cross-guild calendar holds several guilds'
// calendars and projects, and their ids collide.
const keyOf = (guildId: Id, id: number): string => `${guildId ?? 0}:${id}`;

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
    };
  } catch {
    return { calendars: new Set<string>(), projects: new Set<string>() };
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

/**
 * Which calendars, and which projects' task calendars, the reader has switched
 * off, kept under `storageKey`. Stored as the hidden sets so a calendar or
 * project that turns up later is shown.
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
      })
    );
  }, [current]);

  // Stable across renders: they only write through the state setter.
  const actions = useMemo(
    () => ({
      toggleCalendar: (guildId: Id, calendarId: number) => {
        const key = keyOf(guildId, calendarId);
        setState((prev) => ({
          ...prev,
          calendars: withKey(prev.calendars, key, !prev.calendars.has(key)),
        }));
      },
      toggleProject: (guildId: Id, projectId: number) => {
        const key = keyOf(guildId, projectId);
        setState((prev) => ({
          ...prev,
          projects: withKey(prev.projects, key, !prev.projects.has(key)),
        }));
      },
      showCalendar: (guildId: Id, calendarId: number) => {
        const key = keyOf(guildId, calendarId);
        setState((prev) =>
          prev.calendars.has(key)
            ? { ...prev, calendars: withKey(prev.calendars, key, false) }
            : prev
        );
      },
      clear: () => setState((prev) => ({ ...prev, calendars: new Set(), projects: new Set() })),
    }),
    []
  );

  return useMemo(
    () => ({
      ...actions,
      isCalendarHidden: (guildId: Id, calendarId: number) =>
        current.calendars.has(keyOf(guildId, calendarId)),
      isProjectHidden: (guildId: Id, projectId: number) =>
        current.projects.has(keyOf(guildId, projectId)),
      hiddenCount: current.calendars.size + current.projects.size,
    }),
    [actions, current]
  );
};
