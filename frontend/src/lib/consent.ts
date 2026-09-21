/**
 * What this browser has been told it may keep, and the one question the rest
 * of the app asks before loading anything that isn't essential.
 *
 * Two rules hold the whole thing up:
 *
 * 1. **Nothing optional runs until it was asked for.** {@link hasConsent}
 *    answers `false` for every optional category until somebody grants it, so
 *    a category nobody has answered behaves exactly like one that was refused.
 * 2. **Refusing is one click, like accepting.** There is no state where the
 *    only way out of the chooser is to agree.
 *
 * The answer is kept in this browser and goes nowhere else. Somebody reading
 * the landing page has no account to attach it to, and the answer only governs
 * what that browser loads, so a copy on the server would be a second record of
 * a person who has not identified themselves.
 */

import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "cookie-consent";

/**
 * Bump when the categories change, or when one starts covering something it
 * did not before. An older answer stops counting and the question is put
 * again — an answer about a shorter list was never an answer about this one.
 */
export const CONSENT_VERSION = 1;

export const ConsentCategory = {
  /** Sign-in, your preferences, the things the app cannot run without. */
  necessary: "necessary",
  /** How the app gets used, in aggregate. */
  analytics: "analytics",
  /** Measuring what brought somebody here, and reaching them elsewhere. */
  marketing: "marketing",
} as const;

export type ConsentCategory = (typeof ConsentCategory)[keyof typeof ConsentCategory];

/**
 * The categories somebody can actually answer, in the order they are offered.
 *
 * `necessary` is deliberately absent: it is the app working, there is no
 * version of Initiative without it, and a switch that cannot move is a switch
 * that pretends a choice exists.
 */
export const OPTIONAL_CONSENT_CATEGORIES = [
  ConsentCategory.analytics,
  ConsentCategory.marketing,
] as const;

export interface ConsentRecord {
  /** Which {@link CONSENT_VERSION} was answered. */
  readonly version: number;
  /** When, so the deployment can say what was agreed and when. */
  readonly decidedAt: string;
  readonly granted: readonly ConsentCategory[];
}

interface ConsentState {
  /** What was decided, or null where the question is still open. */
  readonly record: ConsentRecord | null;
  /** Whether the chooser was asked for again, having already been answered. */
  readonly reopened: boolean;
}

const isCategory = (value: unknown): value is ConsentCategory =>
  typeof value === "string" && value in ConsentCategory;

/** A stored answer, or null where there is none, it is unreadable, or it
 *  answered an older version of the question. */
const parseRecord = (raw: string | null): ConsentRecord | null => {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { version, decidedAt, granted } = parsed as Partial<ConsentRecord>;
    if (version !== CONSENT_VERSION || typeof decidedAt !== "string") return null;
    if (!Array.isArray(granted)) return null;
    return { version, decidedAt, granted: granted.filter(isCategory) };
  } catch {
    // Unreadable reads as unanswered, which puts the question rather than
    // assuming an answer nobody can produce.
    return null;
  }
};

/** Whether the chooser was asked for again. In memory only: it is about this
 *  page, not about what was decided. */
let reopened = false;

/** The last raw value read, and the state built from it. Storage is the truth
 *  rather than anything held here, so a second tab answering the question is
 *  picked up on the next render instead of two tabs disagreeing until one of
 *  them is reloaded. The pair is cached only so the object handed to
 *  `useSyncExternalStore` keeps its identity between unchanged reads. */
let cachedRaw: string | null | undefined;
let cachedState: ConsentState = { record: null, reopened: false };

const listeners = new Set<() => void>();

const announce = () => {
  for (const listener of listeners) listener();
};

export const subscribeToConsent = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** The same object back while nothing has changed, so `useSyncExternalStore`
 *  can compare it. */
export const getConsentState = (): ConsentState => {
  const raw = getItem(STORAGE_KEY);
  if (raw !== cachedRaw || cachedState.reopened !== reopened) {
    cachedRaw = raw;
    cachedState = { record: parseRecord(raw), reopened };
  }
  return cachedState;
};

/**
 * Whether this browser may be used for `category`.
 *
 * The question to ask before loading anything that is not essential — from
 * React or from a plain module, which is why it is a function and not a hook.
 * Unanswered reads the same as refused.
 */
export const hasConsent = (category: ConsentCategory): boolean => {
  if (category === ConsentCategory.necessary) return true;
  return getConsentState().record?.granted.includes(category) ?? false;
};

/**
 * Record an answer, and say which categories it took back.
 *
 * A script that has already loaded cannot be unloaded, so a caller that sees
 * something in `revoked` rebuilds the page without it.
 */
export const recordConsent = (
  granted: readonly ConsentCategory[]
): { revoked: ConsentCategory[] } => {
  const kept = OPTIONAL_CONSENT_CATEGORIES.filter((category) => granted.includes(category));
  const revoked = OPTIONAL_CONSENT_CATEGORIES.filter(
    (category) => hasConsent(category) && !kept.includes(category)
  );
  const record: ConsentRecord = {
    version: CONSENT_VERSION,
    decidedAt: new Date().toISOString(),
    granted: kept,
  };
  setItem(STORAGE_KEY, JSON.stringify(record));
  reopened = false;
  announce();
  return { revoked };
};

/** Put the question again, from a footer link or the settings page. Taking an
 *  answer back has to be as easy as giving one, so this needs no account and
 *  works wherever the chooser is mounted. */
export const reopenConsent = (): void => {
  reopened = true;
  announce();
};

/** Close a chooser that was reopened, leaving the existing answer alone. A
 *  chooser opened because nobody has answered does not close this way — there
 *  is nothing yet to leave alone. */
export const dismissReopenedConsent = (): void => {
  reopened = false;
  announce();
};
