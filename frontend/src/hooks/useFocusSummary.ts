import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { addDays, endOfDay, startOfDay } from "date-fns";
import { useCallback, useEffect, useMemo } from "react";

import type {
  FilterCondition,
  FilterGroup,
  ListMyTasksApiV1MeTasksGetParams,
  TaskListRead,
  TaskListResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListMyTasksApiV1MeTasksGetQueryKey,
  listMyTasksApiV1MeTasksGet,
} from "@/api/generated/tasks/tasks";
import { useAuth } from "@/hooks/useAuth";
import { useLiveClockValue } from "@/hooks/useRelativeTime";
import { useViewPreference } from "@/hooks/useViewPreference";

/** A pinned task, addressed by guild because task ids collide across guilds. */
export type FocusPin = {
  guild_id: number | null;
  task_id: number;
};

export type FocusPreferences = {
  /** Section expanded or collapsed. */
  open: boolean;
  /** Include tasks due within this many days (0 = due today or overdue). */
  dueWithinDays: number;
  /** Also include urgent/high priority tasks regardless of their due date. */
  includeHighPriority: boolean;
  pins: FocusPin[];
};

export const FOCUS_PREFERENCES_KEY = "my-tasks:focus";

export const FOCUS_DEFAULTS: FocusPreferences = {
  open: true,
  dueWithinDays: 2,
  includeHighPriority: true,
  pins: [],
};

export const FOCUS_DUE_WITHIN_CHOICES = [0, 2, 7] as const;

const URGENT_PRIORITIES = ["urgent", "high"];
/**
 * The API's per-page maximum. There is deliberately no display cap on top of
 * it: a task either meets the rules and belongs on the list, or it does not.
 * Shortening an over-long list is the date window's job, not a hidden cutoff's.
 */
const FETCH_SIZE = 100;

const pinKey = (guildId: number | null | undefined, taskId: number) =>
  `${guildId ?? "none"}:${taskId}`;

/**
 * Conditions for the rule-driven half of the section: open work that is due
 * soon or explicitly urgent, plus anything finished today so completions stay
 * visible instead of vanishing the moment they're checked off.
 *
 * Exported for testing — the OR nesting is the part worth pinning down.
 */
export function buildFocusConditions({
  dueBefore,
  includeHighPriority,
  completedSince,
}: {
  dueBefore: Date;
  includeHighPriority: boolean;
  completedSince: Date;
}): FilterGroup[] {
  // Everything here keys off the caller's own assignment rather than the task's
  // status. Work someone else finished, or that closed while you were away,
  // drops off because closing a task finishes every assignee's part — so this
  // needs no status filter of its own.
  const stillMine: FilterCondition = { field: "my_completion", op: "is_null", value: true };

  // "Mine AND (due soon OR urgent)" is written as sibling AND legs rather than
  // nesting an OR inside the AND: the API caps condition nesting at two group
  // levels and rejects a third outright. Distributing the shared leg costs one
  // duplicated leaf and keeps the same meaning.
  const legs: (FilterCondition | FilterGroup)[] = [
    {
      logic: "and",
      conditions: [stillMine, { field: "due_date", op: "lte", value: dueBefore.toISOString() }],
    },
  ];

  if (includeHighPriority) {
    legs.push({
      logic: "and",
      conditions: [stillMine, { field: "priority", op: "in_", value: URGENT_PRIORITIES }],
    });
  }

  // Today's finished work, kept on the list as the day's progress.
  legs.push({ field: "my_completion", op: "gte", value: completedSince.toISOString() });

  return [{ logic: "or", conditions: legs }];
}

/**
 * When the viewer finished their own part, or null while it is still theirs.
 *
 * Completion is per assignment, so this is deliberately blind to what everyone
 * else has done: a co-assignee finishing their share never clears the task off
 * your list.
 */
export const myCompletion = (task: TaskListRead, viewerId: number | undefined) =>
  task.assignees.find((assignee) => assignee.id === viewerId)?.completed_at ?? null;

const completedOnOrAfter = (task: TaskListRead, viewerId: number | undefined, since: number) => {
  const at = myCompletion(task, viewerId);
  return at != null && new Date(at).getTime() >= since;
};

const byDueDate = (a: TaskListRead, b: TaskListRead) => {
  // Undated work sorts last: it has no clock pressure, so it should never
  // displace something with a deadline.
  if (!a.due_date && !b.due_date) return a.id - b.id;
  if (!a.due_date) return 1;
  if (!b.due_date) return -1;
  return a.due_date.localeCompare(b.due_date);
};

/**
 * The "Focus summary" data: a small, capped set of work that needs doing now,
 * plus today's completions.
 *
 * Two queries rather than one, deliberately. Pins are addressed by
 * (guild, task) but `/me/tasks` filters run per guild against a shared id
 * space, so an `id IN (…)` leg matches same-numbered tasks in *other* guilds
 * too; the pin query over-fetches and is narrowed here. Folding it into the
 * rule query would also push pinned-but-not-urgent work past the fetch window
 * whenever the rules match a lot.
 */
export function useFocusSummary({ enabled = true }: { enabled?: boolean } = {}) {
  const [prefsRaw, setPrefs, { isLoaded }] = useViewPreference<FocusPreferences>(
    FOCUS_PREFERENCES_KEY,
    FOCUS_DEFAULTS
  );

  // A stored blob predates any later field, and is user-writable via the API.
  const prefs = useMemo<FocusPreferences>(
    () => ({
      ...FOCUS_DEFAULTS,
      ...prefsRaw,
      pins: Array.isArray(prefsRaw?.pins) ? prefsRaw.pins : [],
    }),
    [prefsRaw]
  );

  const { user } = useAuth();
  const viewerId = user?.id;

  const timezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // Local midnight, off the shared clock: the list starts clean each morning,
  // so a tab left open overnight rolls over on its own instead of showing
  // yesterday's finished work. The value only changes when the day does, so it
  // costs no re-renders in between (and a fresh `new Date()` per render would
  // churn the query key continuously).
  const today = useLiveClockValue((now) => startOfDay(now).getTime());

  const ruleParams = useMemo<ListMyTasksApiV1MeTasksGetParams>(
    () => ({
      conditions: buildFocusConditions({
        dueBefore: endOfDay(addDays(new Date(today), prefs.dueWithinDays)),
        includeHighPriority: prefs.includeHighPriority,
        completedSince: new Date(today),
      }),
      page: 1,
      page_size: FETCH_SIZE,
      sorting: [{ field: "due_date", dir: "asc" }],
      tz: timezone,
    }),
    [today, prefs.dueWithinDays, prefs.includeHighPriority, timezone]
  );

  const ruleQuery = useQuery<TaskListResponse>({
    queryKey: getListMyTasksApiV1MeTasksGetQueryKey(ruleParams),
    queryFn: () => listMyTasksApiV1MeTasksGet(ruleParams),
    enabled: enabled && isLoaded,
    placeholderData: keepPreviousData,
  });

  const pinnedIds = useMemo(
    () => [...new Set(prefs.pins.map((pin) => pin.task_id))].sort((a, b) => a - b),
    [prefs.pins]
  );

  const pinParams = useMemo<ListMyTasksApiV1MeTasksGetParams>(
    () => ({
      conditions: [{ field: "id", op: "in_", value: pinnedIds }],
      page: 1,
      page_size: FETCH_SIZE,
      tz: timezone,
    }),
    [pinnedIds, timezone]
  );

  const pinQuery = useQuery<TaskListResponse>({
    queryKey: getListMyTasksApiV1MeTasksGetQueryKey(pinParams),
    queryFn: () => listMyTasksApiV1MeTasksGet(pinParams),
    enabled: enabled && isLoaded && pinnedIds.length > 0,
    placeholderData: keepPreviousData,
  });

  const isPinned = useCallback(
    (task: Pick<TaskListRead, "id" | "guild_id">) =>
      prefs.pins.some(
        (pin) => pinKey(pin.guild_id, pin.task_id) === pinKey(task.guild_id, task.id)
      ),
    [prefs.pins]
  );

  const togglePin = useCallback(
    (task: Pick<TaskListRead, "id" | "guild_id">) => {
      const key = pinKey(task.guild_id, task.id);
      setPrefs((prev) => {
        const current = Array.isArray(prev?.pins) ? prev.pins : [];
        const without = current.filter((pin) => pinKey(pin.guild_id, pin.task_id) !== key);
        return {
          ...FOCUS_DEFAULTS,
          ...prev,
          pins:
            without.length === current.length
              ? [...current, { guild_id: task.guild_id ?? null, task_id: task.id }]
              : without,
        };
      });
    },
    [setPrefs]
  );

  const setPreference = useCallback(
    <K extends keyof FocusPreferences>(key: K, value: FocusPreferences[K]) => {
      setPrefs((prev) => ({ ...FOCUS_DEFAULTS, ...prev, [key]: value }));
    },
    [setPrefs]
  );

  const derived = useMemo(() => {
    const ruleItems = ruleQuery.data?.items ?? [];
    const pinItems = (pinQuery.data?.items ?? []).filter((task) => isPinned(task));

    const seen = new Set<string>();
    const pinned: TaskListRead[] = [];
    for (const task of pinItems) {
      const key = pinKey(task.guild_id, task.id);
      if (seen.has(key)) continue;
      seen.add(key);
      pinned.push(task);
    }

    // Done means *my* part is done. A task can be wide open and still belong in
    // the day's wins, because someone else now has it.
    const mineIsFinished = (task: TaskListRead) => myCompletion(task, viewerId) != null;

    const openMatches: TaskListRead[] = [];
    const completedToday: TaskListRead[] = [];
    for (const task of ruleItems) {
      const key = pinKey(task.guild_id, task.id);
      if (seen.has(key)) continue;
      seen.add(key);
      (mineIsFinished(task) ? completedToday : openMatches).push(task);
    }

    // A pinned task finished today belongs with the day's wins rather than the
    // list of things still to do. One finished on an earlier day is settled
    // business: the list starts clean each morning, so it drops off entirely
    // (the pin query carries no date filter of its own, unlike the rule query).
    const pinnedOpen = pinned.filter((task) => !mineIsFinished(task));
    const pinnedDoneToday = pinned.filter((task) => completedOnOrAfter(task, viewerId, today));
    const finishedEarlier = pinned.filter(
      (task) => mineIsFinished(task) && !completedOnOrAfter(task, viewerId, today)
    );

    openMatches.sort(byDueDate);

    return {
      pinned: pinnedOpen,
      upcoming: openMatches,
      completedToday: [...pinnedDoneToday, ...completedToday].sort(byDueDate),
      finishedEarlier,
      // The rules matched more than one page. Rare, and not something the
      // section decides — but say so rather than quietly showing a prefix.
      truncated: (ruleQuery.data?.total_count ?? 0) > ruleItems.length,
    };
  }, [ruleQuery.data, pinQuery.data, isPinned, today, viewerId]);

  // Drop pins the user has already finished on an earlier day, so the blob
  // doesn't accumulate them and the pin query stays small. Only pins we
  // positively resolved are removed — an absent one may just be out of reach
  // for now, and forgetting it would silently lose the user's choice.
  const staleIds = derived.finishedEarlier.map((task) => pinKey(task.guild_id, task.id)).join("|");
  useEffect(() => {
    if (!staleIds) return;
    const stale = new Set(staleIds.split("|"));
    setPrefs((prev) => ({
      ...FOCUS_DEFAULTS,
      ...prev,
      pins: (Array.isArray(prev?.pins) ? prev.pins : []).filter(
        (pin) => !stale.has(pinKey(pin.guild_id, pin.task_id))
      ),
    }));
  }, [staleIds, setPrefs]);

  const remainingCount = derived.pinned.length + derived.upcoming.length;
  const doneCount = derived.completedToday.length;
  // `finishedEarlier` only feeds the pruning effect above; it is not part of
  // what the section renders.
  const { finishedEarlier: _finishedEarlier, ...visible } = derived;

  return {
    ...visible,
    prefs,
    setPreference,
    isPinned,
    togglePin,
    /** Everything on today's list, done or not — the progress denominator. */
    totalCount: remainingCount + doneCount,
    doneCount,
    isLoading: isLoaded && ruleQuery.isPending,
    hasError: ruleQuery.isError,
    isEmpty: remainingCount === 0 && doneCount === 0,
  };
}
