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
 * Point React Query's online state at the device.
 *
 * Deliberately does not await the first reading: this runs on the boot path,
 * and a plugin call that never settles there is one that strands the app (see
 * the awaits in `main.tsx`). The listener is installed synchronously and the
 * first status corrects it a moment later — before any query runs, because the
 * persisted cache has to be read from IndexedDB first either way.
 */
export const bindOnlineManagerToDevice = (): void => {
  if (!needsNativeBinding()) return;

  onlineManager.setEventListener((setOnline) => {
    let handle: PluginListenerHandle | null = null;
    let cancelled = false;

    Network.addListener("networkStatusChange", (status) => setOnline(status.connected))
      .then((registered) => {
        if (cancelled) {
          void registered.remove();
        } else {
          handle = registered;
        }
      })
      .catch(() => {
        // Without the listener React Query keeps its own detection, which is
        // the behaviour we had before this existed rather than a new failure.
      });

    Network.getStatus()
      .then((status) => setOnline(status.connected))
      .catch(() => {
        // A status we could not read is not evidence of being offline, and
        // claiming it would pause every query on a working connection.
      });

    return () => {
      cancelled = true;
      if (handle) void handle.remove();
    };
  });
};
