/**
 * Document badges — a chip that shows what a thing is doing right now.
 *
 * A `#` mention stores a label and is finished. A badge stores a *reference*
 * and never is: the document holds the pointer, the server holds the truth, and
 * the chip re-reads it. Moving a card changes every badge pointing at it,
 * in every document, without any of them being edited.
 *
 * What can be badged is `BadgeKind` — generated from the server's own registry,
 * so this file cannot offer one nothing answers.
 */

import {
  BadgeKind,
  type BadgeState,
  BadgeTone,
  type SearchEntityType,
} from "@/api/generated/initiativeAPI.schemas";

/** How the parts of a reference are joined — mirrors `REF_SEPARATOR`. */
const SEPARATOR = ":";

/** Every badge that can be inserted, in menu order. */
export const BADGE_KINDS: BadgeKind[] = Object.values(BadgeKind);

/** Whether a stored string still names a badge this build offers. */
export const isBadgeKind = (value: string): value is BadgeKind =>
  (BADGE_KINDS as string[]).includes(value);

/** The thing a badge is about. */
export const badgeEntityType = (kind: BadgeKind): SearchEntityType =>
  kind.split(SEPARATOR)[0] as SearchEntityType;

/** The changing fact it shows. */
export const badgeAspect = (kind: BadgeKind): string => kind.split(SEPARATOR)[1];

/** What a document stores for one chip: `task:12:status`. */
export const badgeRef = (kind: BadgeKind, entityId: number): string =>
  `${badgeEntityType(kind)}${SEPARATOR}${entityId}${SEPARATOR}${badgeAspect(kind)}`;

/**
 * The classes a tone renders in.
 *
 * The server decides the tone because what counts as finished or late is a
 * product rule; this decides only what that looks like. A chip whose thing
 * carries its own colour ignores all of it.
 *
 * Every colour here is a theme token, so a chip follows the reader's theme the
 * way the rest of the app does rather than carrying a fixed palette with a
 * dark-mode patch bolted on.
 */
export const BADGE_TONE_CLASSES: Record<BadgeTone, string> = {
  [BadgeTone.neutral]: "bg-muted text-muted-foreground",
  [BadgeTone.muted]: "bg-muted/60 text-muted-foreground/80",
  [BadgeTone.good]: "bg-success/15 text-success",
  [BadgeTone.warn]: "bg-warning/15 text-warning",
  [BadgeTone.danger]: "bg-destructive/15 text-destructive",
};

/**
 * What a chip shows, given what came back for it.
 *
 * A state that did not come back is a thing that is gone or that this reader
 * cannot open — the same answer either way — so the chip falls back to the
 * label the document stored beside it, with nothing claimed about its state.
 */
export interface BadgeDisplay {
  text: string;
  className: string;
  /** Set only where the thing carries its own colour. */
  color?: string;
}

export const badgeDisplay = (
  fallback: string,
  state: BadgeState | undefined,
  formatDate: (iso: string) => string,
  emptyLabel: string
): BadgeDisplay => {
  // Nothing came back: the thing is gone, or out of this reader's reach. The
  // label the document stored is all there is to show.
  if (!state) {
    return { text: fallback, className: BADGE_TONE_CLASSES[BadgeTone.muted] };
  }
  // An answered chip with nothing in it — an unassigned task, a date not set —
  // says so. Falling back to the stored label here would put the task's title
  // where its assignee goes.
  if (!state.text && !state.date && state.number == null) {
    return { text: emptyLabel, className: BADGE_TONE_CLASSES[state.tone] };
  }
  // A date and a number belong in the reader's locale, which only the browser
  // knows; the server's `text` is what stands in until it is formatted.
  return {
    text: state.date ? formatDate(state.date) : state.text,
    className: BADGE_TONE_CLASSES[state.tone],
    color: state.color ?? undefined,
  };
};
