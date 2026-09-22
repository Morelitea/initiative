import { useEffect, useSyncExternalStore } from "react";

import { useAuth } from "@/hooks/useAuth";
import {
  getTimeFormat,
  notifyTimeFormat,
  parseTimeFormat,
  subscribeTimeFormat,
  type TimeFormatPreference,
  writeTimeFormat,
} from "@/lib/timeFormat";

/**
 * The account's clock convention, re-rendering the caller when it changes.
 *
 * Use this in a component that *derives* something from the preference — a
 * format string, a list of labelled time slots, a memo holding a formatted
 * string. A component that calls a formatter inline needs nothing: the
 * formatter reads the same store, which is already up to date by the time
 * anything below the root renders.
 */
export const useTimeFormat = (): TimeFormatPreference =>
  useSyncExternalStore(subscribeTimeFormat, getTimeFormat, getTimeFormat);

/**
 * Copies the signed-in account's preference into the module store the
 * formatters read. Mounted once, at the root.
 */
export const useTimeFormatSync = (): void => {
  const { user } = useAuth();
  const preference = parseTimeFormat(user?.time_format);

  // Written during the root's render, not in an effect. The formatters are
  // plain functions and most of their callers never subscribe, so a value
  // applied after the commit would leave the whole tree on the previous clock
  // until something unrelated re-rendered it — which is exactly what happens
  // on the first load, when the account arrives after the first paint. The
  // root renders before everything under it, so writing here puts every
  // timestamp in the same pass on the right clock. The write is idempotent,
  // which is what makes it safe to repeat.
  writeTimeFormat(preference);

  // Subscribers are told after the commit, because telling them mid-render
  // would be asking other components to re-render while this one is rendering.
  // Keyed on the preference rather than on whether the write changed anything:
  // a double-invoked render would report "unchanged" on its second pass and
  // nobody would ever hear about the first.
  useEffect(() => {
    notifyTimeFormat();
  }, [preference]);
};
