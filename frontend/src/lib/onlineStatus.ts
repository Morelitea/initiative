import { Capacitor, type PluginListenerHandle } from "@capacitor/core";
import { Network } from "@capacitor/network";
import { onlineManager } from "@tanstack/react-query";

/**
 * Teach React Query what "offline" means on a phone.
 *
 * React Query decides on its own whether to run a fetch: with the default
 * `networkMode: "online"` it holds a query as `paused` while there is no
 * network, leaving whatever is already on screen — which, after a restore from
 * the offline cache, is the content this device last loaded. That behaviour is
 * the whole reason offline reading looks like reading rather than a page of
 * errors.
 *
 * Left alone it decides from `navigator.onLine`, which inside an Android
 * WebView commonly stays `true` with no connectivity at all. The queries then
 * run, fail, retry, fail, and land in `error` — so a device with no signal
 * shows "unable to load" over cached content that was sitting right there.
 * `useNetworkStatus` already reads the real thing for the offline banner, which
 * is how the banner could be right while the page under it was wrong.
 *
 * So on native the plugin becomes the source of truth for both.
 */

/** Whether the two sources of truth need reconciling here. Web's default is already correct. */
const needsNativeBinding = (): boolean => Capacitor.isNativePlatform();

/**
 * How long boot will wait for the device's first answer.
 *
 * Bounded on purpose. The first reading has to be in hand before anything can
 * query, or the very race this exists to prevent happens during the gap. But
 * this runs on the boot path, where a plugin call that never settles is a
 * plugin call that strands the app behind the splash screen — so the wait
 * gives up rather than being open-ended, and boot continues on React Query's
 * own detection, which is what it used before any of this existed.
 */
const FIRST_STATUS_TIMEOUT_MS = 2_000;

/** The device's current answer, or `null` for "could not say in time". */
const firstStatus = async (): Promise<boolean | null> => {
  try {
    return await Promise.race([
      Network.getStatus().then((status) => status.connected),
      new Promise<null>((resolve) => {
        setTimeout(() => resolve(null), FIRST_STATUS_TIMEOUT_MS);
      }),
    ]);
  } catch {
    // A status we could not read is not evidence of being offline, and claiming
    // it would pause every query on a working connection.
    return null;
  }
};

/**
 * Point React Query's online state at the device.
 *
 * Awaited by the boot path: the first reading is applied *before* the change
 * listener is installed, so there is no window in which a stale snapshot can
 * land on top of a newer event, and no window in which a query runs against
 * the WebView's wrong answer.
 */
export const bindOnlineManagerToDevice = async (): Promise<void> => {
  if (!needsNativeBinding()) return;

  const connected = await firstStatus();

  onlineManager.setEventListener((setOnline) => {
    let handle: PluginListenerHandle | null = null;
    let cancelled = false;
    let removeFallback: (() => void) | null = null;

    // Installing an event listener takes React Query's own off. If the plugin
    // will not give us one, something still has to report a change, so the
    // browser's events — unreliable here, but not nothing — take over rather
    // than leaving the app with no source at all until it is restarted.
    const fallBackToBrowserEvents = () => {
      const goOnline = () => setOnline(true);
      const goOffline = () => setOnline(false);
      window.addEventListener("online", goOnline);
      window.addEventListener("offline", goOffline);
      removeFallback = () => {
        window.removeEventListener("online", goOnline);
        window.removeEventListener("offline", goOffline);
      };
    };

    Network.addListener("networkStatusChange", (status) => setOnline(status.connected))
      .then((registered) => {
        if (cancelled) {
          void registered.remove();
        } else {
          handle = registered;
        }
      })
      .catch(() => {
        if (!cancelled) fallBackToBrowserEvents();
      });

    return () => {
      cancelled = true;
      if (handle) void handle.remove();
      removeFallback?.();
    };
  });

  // After the listener, so the two cannot be applied out of order — and
  // synchronously after it, so no event can arrive in between.
  if (connected !== null) onlineManager.setOnline(connected);
};
