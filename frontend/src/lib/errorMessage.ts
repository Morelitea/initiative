import type { AxiosError } from "axios";
import { isAxiosError } from "axios";

import i18n from "@/i18n";

/** Loose translation function that accepts dynamic keys without strict type checking. */
const translate = i18n.t.bind(i18n) as (key: string, options?: Record<string, unknown>) => string;

/** One entry of FastAPI's 422 body: `{"detail": [{type, loc, msg}, ...]}`. */
interface ValidationDetail {
  msg?: string;
  loc?: (string | number)[];
}

/**
 * The flat error code inside a pydantic validation message, if there is one.
 *
 * A validator that raises `ValueError("SOME_CODE")` reaches the client as
 * `"Value error, SOME_CODE"`. Everything else — a length or type failure —
 * has no code to pull out, so this returns null and the caller falls back.
 */
function codeFromValidationDetail(detail: ValidationDetail[]): string | null {
  for (const entry of detail) {
    const match = /^Value error,\s*([A-Z][A-Z0-9_]*)$/.exec(entry?.msg?.trim() ?? "");
    if (match) return match[1];
  }
  return null;
}

/**
 * Extract a user-facing error message from an API error response.
 *
 * Tries to map a backend error code (from `detail`) to a localized string
 * in the `errors` namespace. A 422 carries a list of field errors instead;
 * a flat code raised by a validator is localized the same way. Falls back to
 * the provided fallback key or the raw detail string.
 */
export function getErrorMessage(error: unknown, fallbackKey?: string): string {
  const axiosError = error as AxiosError<{ detail?: string | ValidationDetail[] }>;

  // slowapi returns 429 with {"error": "..."} instead of {"detail": "..."}
  if (axiosError?.response?.status === 429) {
    return translate("RATE_LIMITED", { ns: "errors" });
  }

  const detail = axiosError?.response?.data?.detail;

  // A 422 carries a list of field errors rather than a code. Localize the flat
  // code a validator raised; otherwise fall through to the caller's fallback,
  // since pydantic's own wording is not written for an end user.
  if (Array.isArray(detail)) {
    const code = codeFromValidationDetail(detail);
    if (code) {
      const localized = translate(code, { ns: "errors", defaultValue: "" });
      if (localized) return localized;
    }
    return fallbackKey ? translate(fallbackKey) : translate("fallback", { ns: "errors" });
  }

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

/**
 * The backend error code carried in `detail`, if the error has one.
 *
 * For the callers that have to branch on *which* failure it was rather than
 * just show it — the codes (`app/core/messages.py`) are the machine-readable
 * half of the same contract `getErrorMessage` localizes.
 */
export function getErrorCode(error: unknown): string | null {
  if (!isAxiosError(error)) {
    return null;
  }
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
  if (Array.isArray(detail)) {
    return codeFromValidationDetail(detail as ValidationDetail[]);
  }
  return typeof detail === "string" ? detail : null;
}

/**
 * Extract the HTTP status code from an error, if available.
 */
export function getHttpStatus(error: unknown): number | null {
  if (isAxiosError(error)) {
    return error.response?.status ?? null;
  }
  return null;
}
