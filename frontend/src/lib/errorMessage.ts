import type { AxiosError } from "axios";
import i18n from "@/i18n";

/** Loose translation function that accepts dynamic keys without strict type checking. */
const translate = i18n.t.bind(i18n) as (key: string, options?: Record<string, unknown>) => string;

/**
 * Extract a user-facing error message from an API error response.
 *
 * Tries to map a backend error code (from `detail`) to a localized string
 * in the `errors` namespace. Falls back to the provided fallback key or
 * the raw detail string.
 */
export function getErrorMessage(error: unknown, fallbackKey?: string): string {
  const axiosError = error as AxiosError<{ detail?: string }>;
  const detail = axiosError?.response?.data?.detail;

  if (detail) {
    // Try to look up the detail as a key in the errors namespace
    const localized = translate(detail, { ns: "errors", defaultValue: "" });
    if (localized) {
      return localized;
    }
    // If it's not a known error code, return the raw detail string
    return detail;
  }

  if (fallbackKey) {
    return translate(fallbackKey);
  }

  return translate("fallback", { ns: "errors" });
}
