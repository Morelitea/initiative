import type { AxiosError } from "axios";
import i18n from "@/i18n";

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
    const localized = i18n.t(detail, { ns: "errors", defaultValue: "" });
    if (localized) {
      return localized;
    }
    // If it's not a known error code, return the raw detail string
    return detail;
  }

  if (fallbackKey) {
    return i18n.t(fallbackKey);
  }

  return i18n.t("fallback", { ns: "errors" });
}
