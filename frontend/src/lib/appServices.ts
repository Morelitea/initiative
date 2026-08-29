/**
 * Vocabularies for deployment-level app service registrations.
 *
 * The backend stores `status` and `grants` as plain strings rather than
 * enums, so nothing lands in the generated schema types. These mirror
 * `app.models.platform.app_service_registration` and must move with it.
 */

import type { AppServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";

/**
 * Where a registration stands with its container.
 *
 * `unverified` is the resting state of a row that has never completed a
 * handshake — the ordinary case for an app wired up before its container
 * boots, not a failure.
 */
export const APP_SERVICE_STATUSES = [
  "ok",
  "unverified",
  "unreachable",
  "manifest_mismatch",
  "signature_mismatch",
] as const;

export type AppServiceStatus = (typeof APP_SERVICE_STATUSES)[number];

/** Narrow a server-supplied status, so an unknown one renders as itself. */
export const isAppServiceStatus = (value: string): value is AppServiceStatus =>
  (APP_SERVICE_STATUSES as readonly string[]).includes(value);

/**
 * Powers the operator confers on a registration. A manifest never claims
 * one — a manifest is the publisher's statement, a registration is the
 * operator's.
 *
 * `delegation` lets the app call the API as a real member, under that
 * member's own gates. `app_directory` lets it ask where another app
 * installed in the same guild answers; the two are separate because acting
 * for a member has no call to read another app's address. An automation
 * service holds both, and the route that serves an address asks for both.
 *
 * Every value here has a control in the settings form. One the backend adds
 * that this build has not caught up with is carried through a save untouched
 * — see `mergeGrants`.
 */
export const APP_SERVICE_GRANTS = ["delegation", "app_directory"] as const;

export type AppServiceGrant = (typeof APP_SERVICE_GRANTS)[number];

export const hasGrant = (
  registration: Pick<AppServiceRegistrationRead, "grants">,
  grant: AppServiceGrant
): boolean => registration.grants.includes(grant);

/**
 * The grant list a save should send: what the form states, plus anything
 * already stored that this build has no control for.
 *
 * A PATCH replaces `grants` wholesale, so a form that rebuilds the list from
 * the controls it happens to render takes away every power it cannot show.
 * Carrying the rest through means an older frontend against a newer backend
 * edits a base URL without also revoking something.
 */
export const mergeGrants = (
  stated: readonly AppServiceGrant[],
  stored: readonly string[] | undefined
): string[] => [
  ...stated,
  ...(stored ?? []).filter((grant) => !(APP_SERVICE_GRANTS as readonly string[]).includes(grant)),
];

/**
 * The backend error code carried on a refusal, or null when the failure
 * has no code (a transport error, or a shape this build doesn't produce).
 * Lets a caller branch on a specific outcome — the changed-manifest case —
 * where a rendered message would not be enough.
 */
export const appServiceErrorCode = (error: unknown): string | null => {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null | undefined)
    ?.response?.data?.detail;
  return typeof detail === "string" ? detail : null;
};

/** Raised when the served manifest no longer matches the recorded hash. */
export const APP_SERVICE_MANIFEST_CHANGED = "APP_SERVICE_MANIFEST_CHANGED";

/** Split a textarea of origins into the list the API expects. */
export const parseAllowedOrigins = (value: string): string[] =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
