/**
 * The search param that makes a list view linkable: which of its views it
 * shows, by slug.
 *
 * Tool-agnostic on purpose — nothing here imports `Tool`. A view's slug means
 * the same thing for every tool that has views.
 */

/** Slugs are lowercase kebab, matching what the API derives from a name. */
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_SLUG_LENGTH = 64;

/** Coerce a `?view=` value (or a `?preset=` from before views). Anything
 *  malformed is dropped, never thrown — a pasted link with a typo should still
 *  render the list. */
export const parseViewSlug = (raw: unknown): string | undefined =>
  typeof raw === "string" && raw.length <= MAX_SLUG_LENGTH && SLUG_PATTERN.test(raw)
    ? raw
    : undefined;
