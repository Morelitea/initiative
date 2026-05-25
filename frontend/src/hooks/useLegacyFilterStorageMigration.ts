/**
 * One-shot migration of pre-server-state filter values out of
 * `lib/storage` (localStorage / Capacitor Preferences) and into the new
 * per-user view-preferences endpoint.
 *
 * Runs once per authenticated session per device — guarded by a marker
 * key. For each known legacy key still present locally, if the server
 * doesn't already have a value for the equivalent scope, the local
 * value is uploaded and removed from local storage. Re-runs are no-ops.
 */

import { useEffect, useRef } from "react";

import {
  listViewPreferencesApiV1UserViewPreferencesGet,
  putViewPreferenceApiV1UserViewPreferencesScopeKeyPut,
} from "@/api/generated/user-view-preferences/user-view-preferences";
import { useAuth } from "@/hooks/useAuth";
import { getItem, listKeys, removeItem, setItem } from "@/lib/storage";

const MIGRATION_MARKER_KEY = "initiative-view-prefs-migrated-v1";

/**
 * Legacy keys whose name is identical to the new scope_key. We just
 * upload the parsed JSON verbatim and drop the local copy.
 */
const FLAT_KEYS: readonly string[] = [
  "initiative-my-tasks-filters",
  "initiative-created-tasks-filters",
  "initiative-my-documents-filters",
  "initiative-my-projects-filters",
  "initiative-my-calendar-prefs",
  "initiative-my-calendar-tasks-filters",
  "documents:view-mode",
  "documents:tag-filters",
  "project:list:sort",
  "project:list:search",
  "project:list:view-mode",
  "project:list:tag-filters",
];

/**
 * Per-resource key patterns. The full local key is used verbatim as the
 * scope_key so the mental model and the value's shape stay identical.
 * The patterns just identify which keys to scan for.
 */
const PER_RESOURCE_KEY_PATTERNS: readonly RegExp[] = [
  /^project:\d+:view-filters$/,
  /^counter-group-\d+-layout$/,
];

const isMigratableKey = (key: string): boolean => {
  if (FLAT_KEYS.includes(key)) return true;
  return PER_RESOURCE_KEY_PATTERNS.some((pat) => pat.test(key));
};

/**
 * Plain values (e.g. counter group layout = "row" / "grid") were stored
 * as bare strings, not JSON. Try JSON.parse first; fall back to the raw
 * string so we don't corrupt them.
 */
const parseStoredValue = (raw: string): unknown => {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
};

export function useLegacyFilterStorageMigration(): void {
  const { user } = useAuth();
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current || user === null) return;
    if (getItem(MIGRATION_MARKER_KEY) === "1") {
      ranRef.current = true;
      return;
    }
    ranRef.current = true;

    void (async () => {
      try {
        const serverMap = await listViewPreferencesApiV1UserViewPreferencesGet();
        const existing = new Set(Object.keys(serverMap.items ?? {}));
        const candidates = listKeys().filter(isMigratableKey);

        for (const key of candidates) {
          const raw = getItem(key);
          if (raw === null) continue;
          // Don't clobber whatever already lives on the server — other
          // devices may have set fresher values.
          if (!existing.has(key)) {
            try {
              const value = parseStoredValue(raw);
              await putViewPreferenceApiV1UserViewPreferencesScopeKeyPut(key, { value });
            } catch (err) {
              // Skip individual failures (e.g. payload over the 16 KiB
              // cap); keep the local copy so the user doesn't lose data.
              console.warn("View preference migration skipped", key, err);
              continue;
            }
          }
          removeItem(key);
        }

        setItem(MIGRATION_MARKER_KEY, "1");
      } catch (err) {
        // If the migration request itself fails (e.g. offline), leave
        // the marker unset so we retry next time.
        console.warn("View preference migration failed", err);
        ranRef.current = false;
      }
    })();
  }, [user]);
}
