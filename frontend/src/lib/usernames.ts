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
 * The first word of a display name, reduced to the characters a handle may
 * contain. Returns "" when nothing usable survives — an empty name, one made
 * of punctuation, or an address, which is never the source of a handle.
 */
export const slugifyUsername = (seed: string | null | undefined): string => {
  const text = (seed ?? "").trim();
  if (!text || text.includes("@")) return "";

  const slug = text
    .split(/\s+/)[0]
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
