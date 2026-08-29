/**
 * Turning something a person already typed into a handle we can offer them.
 *
 * A convenience only — the server validates, allocates the number, and is the
 * authority on what a name part may be (`app/core/usernames.py`). This exists
 * so the field can fill itself in as someone types their name.
 */

const MIN_LENGTH = 3;
const MAX_LENGTH = 32;

/**
 * A handle offered from a display name: first initial, then last name —
 * `Lee Janzen` becomes `ljanzen`, the same rule the server seeds with. A
 * single-word name has no last name to join, so it stands on its own.
 *
 * Returns "" when nothing usable survives — an empty name, one made of
 * punctuation, or an address, which is never the source of a handle.
 */
export const slugifyUsername = (seed: string | null | undefined): string => {
  const text = (seed ?? "").trim();
  if (!text || text.includes("@")) return "";

  const tokens = text.split(/\s+/);
  const source = tokens.length === 1 ? tokens[0] : `${tokens[0][0]}${tokens[tokens.length - 1]}`;

  const slug = source
    .normalize("NFKD")
    // Drop combining marks so an accented name keeps its shape instead of
    // collapsing to nothing.
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/[-_]{2,}/g, "-")
    .replace(/^[^a-z]+/, "")
    .replace(/[-_]+$/, "")
    .slice(0, MAX_LENGTH)
    .replace(/[-_]+$/, "");

  return slug.length >= MIN_LENGTH ? slug : "";
};
