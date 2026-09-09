/**
 * Deciding, at startup, whether there is anything to restore.
 *
 * Kept apart from `offlineCache` so that module stays free of any dependency on
 * the session snapshot — `offlineSession` reads the max age from it, and the
 * two would otherwise import each other.
 */

import {
  isOfflineCacheEnabled,
  noteRestoredIdentity,
  offlineCacheBuster,
  offlinePersistOptions,
  purgeOfflineCache,
} from "@/lib/offlineCache";
import { currentServerKey, readOfflineSession } from "@/lib/offlineSession";

/**
 * Prepare the persisted cache for this launch, before React renders.
 *
 * Returns the `persistOptions` for `PersistQueryClientProvider`, or null when
 * offline reading is not enabled here — in which case nothing is restored and
 * nothing is written.
 *
 * A blob with no session snapshot beside it is discarded rather than restored:
 * the snapshot is what says who the content belongs to, and content nobody can
 * be named for is content we should not be showing.
 */
export const prepareOfflineCache = async () => {
  if (!isOfflineCacheEnabled()) {
    return null;
  }

  const serverKey = currentServerKey();
  // Reading also expires it: a snapshot past the window, or from another
  // server, is cleared here rather than left to be reconsidered later.
  const snapshot = readOfflineSession(serverKey);
  noteRestoredIdentity(snapshot?.id ?? null);

  if (!snapshot) {
    await purgeOfflineCache();
  }

  return offlinePersistOptions(offlineCacheBuster(serverKey));
};
