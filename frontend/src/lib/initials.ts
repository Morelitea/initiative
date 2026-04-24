/**
 * Compute display initials from a user's name.
 *
 * - Two or more words → first character of the first two words (e.g.
 *   "Ada Lovelace Hopper" → "AL"). Matches how initials appear on
 *   comment threads, assignee rows, and the collaboration badge.
 * - Single word → the first two characters (e.g. "Ada" → "AD"),
 *   matching the mentions typeahead and calendar list view.
 * - Empty / whitespace-only → first character of the optional
 *   ``fallback`` (typically an email), uppercased. When that's also
 *   missing, returns ``"?"``.
 *
 * Always returns a non-empty, uppercased string so callers can hand the
 * result straight to an ``AvatarFallback`` without further guarding.
 */
export const getInitials = (value?: string | null, fallback?: string | null): string => {
  const name = value?.trim();
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    if (parts.length === 1) {
      return parts[0].slice(0, 2).toUpperCase();
    }
  }
  const fb = fallback?.trim();
  if (fb) {
    return fb[0].toUpperCase();
  }
  return "?";
};
