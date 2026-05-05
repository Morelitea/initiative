/**
 * Shared IANA timezone list for any UI that lets the user pick one
 * (Settings → Profile, Settings → Notifications, …).
 *
 * Prefers ``Intl.supportedValuesOf("timeZone")`` (returns the full
 * IANA list the runtime knows about). Falls back to a small curated
 * set when the API isn't available — old browsers, locked-down
 * environments, or test runners with stripped Intl data.
 */

const FALLBACK_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const resolveTimezones = (): string[] => {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  if (typeof intl.supportedValuesOf === "function") {
    try {
      return intl.supportedValuesOf("timeZone");
    } catch {
      return FALLBACK_TIMEZONES;
    }
  }
  return FALLBACK_TIMEZONES;
};

/** Resolved once at module load — the list doesn't change at runtime. */
export const TIMEZONE_OPTIONS = resolveTimezones();
