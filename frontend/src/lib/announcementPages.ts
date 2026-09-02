import type { AnnouncementSection } from "@/api/generated/initiativeAPI.schemas";

/**
 * Split an announcement's sections into the pages a reader steps through.
 *
 * Sections are one flowing list until a section says `starts_page`, which is
 * what makes a wizard-shaped announcement out of the same data an ordinary one
 * uses: no pages declared, one page. A leading break is not an empty first
 * page — the first section always opens page one.
 */
export const splitIntoPages = (sections: AnnouncementSection[]): AnnouncementSection[][] => {
  const pages: AnnouncementSection[][] = [];
  for (const section of sections) {
    if (pages.length === 0 || section.starts_page) {
      pages.push([section]);
      continue;
    }
    pages[pages.length - 1].push(section);
  }
  return pages;
};

/**
 * What is wrong with a trigger pattern, or `null` if nothing is.
 *
 * The server only checks that a pattern looks like a path, so a mistake in the
 * wildcards it cannot see — `/c/*settings`, or a `**` with something after it —
 * is accepted and then never matches anything. This is the check that catches
 * both, in the form, before a save turns a typo into a 422.
 */
export type TriggerRouteProblem =
  | "needsSlash"
  | "whitespace"
  | "wildcardSegment"
  | "doubleStarNotLast";

export const validateTriggerRoute = (value: string): TriggerRouteProblem | null => {
  const trimmed = value.trim();
  if (!trimmed) {
    // Empty is how you say "show it right away" — the field is optional.
    return null;
  }
  if (!trimmed.startsWith("/") || trimmed.startsWith("//")) {
    return "needsSlash";
  }
  if (/\s/.test(trimmed)) {
    return "whitespace";
  }

  const parts = trimPath(trimmed).split("/");
  // A wildcard stands for a whole segment. Glued to anything else it is just a
  // literal that can never match a real path — reported first, because it is
  // the likelier typo and a pattern can have both problems at once.
  if (parts.some((part) => part.includes("*") && part !== "*" && part !== "**")) {
    return "wildcardSegment";
  }
  if (parts.some((part, index) => part === "**" && index !== parts.length - 1)) {
    return "doubleStarNotLast";
  }
  return null;
};

/**
 * Whether a trigger pattern matches the route the reader is on.
 *
 * The pattern is a path with two wildcards: `*` stands for exactly one segment
 * (`/c/*​/settings` matches any community's settings page) and `**` for the
 * rest of the path (`/c/**` matches everything inside a community). Everything
 * else is compared literally, and a trailing slash is not a difference.
 *
 * Matching lives in the client because routes do: the server stores the
 * pattern and has no opinion about what it means.
 */
export const matchesTriggerRoute = (pattern: string, pathname: string): boolean => {
  const patternParts = trimPath(pattern).split("/");
  const pathParts = trimPath(pathname).split("/");

  for (let index = 0; index < patternParts.length; index += 1) {
    const part = patternParts[index];
    if (part === "**") {
      // Matches the rest, including nothing at all.
      return true;
    }
    if (index >= pathParts.length) {
      return false;
    }
    if (part === "*") {
      continue;
    }
    if (part !== pathParts[index]) {
      return false;
    }
  }
  // Ran out of pattern: the path has to have ended too, or the pattern named a
  // page and the reader is on one below it.
  return patternParts.length === pathParts.length;
};

const trimPath = (value: string): string => value.replace(/\/+$/, "") || "/";
