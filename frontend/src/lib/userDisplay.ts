import type { UserStatus } from "@/api/generated/initiativeAPI.schemas";
import { ANONYMIZED_INITIALS, getInitials } from "@/lib/initials";

/**
 * The minimum shape of a user object needed to render a display name.
 *
 * Anything that comes back from the API and represents a person — guild
 * member, comment author, task assignee, mention candidate, etc. —
 * should fit this shape. ``status`` is optional because some legacy or
 * lightweight endpoints don't include it; absent ``status`` is treated
 * as a live user.
 */
export interface DisplayableUser {
  id?: number | null;
  full_name?: string | null;
  email?: string | null;
  status?: UserStatus | string | null;
}

/**
 * The single source of truth for "what string do we render for this user".
 *
 * - Anonymized → ``"Deleted user #<id>"`` (per-user so multiple deleted
 *   users in a list stay distinguishable without leaking PII).
 * - Otherwise → ``full_name`` if present, else ``email`` if present, else
 *   the supplied ``fallback`` (defaults to ``"User"``).
 *
 * Use this anywhere you would have written
 * ``user.full_name ?? user.email ?? "User"`` so an anonymized user
 * doesn't accidentally render an empty string or the literal "null".
 */
export const getUserDisplayName = (
  user: DisplayableUser | null | undefined,
  fallback = "User"
): string => {
  if (!user) return fallback;
  if (isAnonymizedUser(user)) {
    return user.id != null ? `Deleted user #${user.id}` : "Deleted user";
  }
  const name = user.full_name?.trim();
  if (name) return name;
  const email = user.email?.trim();
  if (email) return email;
  return fallback;
};

/**
 * True when the user's account has been anonymized (PII removed).
 *
 * Centralised so callers don't compare to the magic string everywhere.
 */
export const isAnonymizedUser = (user: DisplayableUser | null | undefined): boolean =>
  user?.status === "anonymized";

/**
 * Initials to render in an avatar fallback for the given user. Returns
 * the muted ``–`` sentinel for anonymized accounts; otherwise delegates
 * to ``getInitials`` with the user's name (or email fallback).
 */
export const getInitialsForUser = (user: DisplayableUser | null | undefined): string => {
  if (!user) return getInitials(undefined);
  if (isAnonymizedUser(user)) return ANONYMIZED_INITIALS;
  return getInitials(user.full_name ?? undefined, user.email ?? undefined);
};
