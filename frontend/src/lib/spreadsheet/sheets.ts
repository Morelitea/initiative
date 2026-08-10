/**
 * Sheet identity for multi-sheet spreadsheet documents.
 *
 * A workbook is an ordered list of sheets. Each sheet carries a stable
 * ``id`` (never shown, never reused — formulas and Yjs containers key off
 * it) and a user-facing ``name`` (shown on the tab, and the thing a
 * cross-sheet formula spells: ``=Sheet2!A1``).
 *
 * Names therefore have to survive a round-trip through formula text, so
 * this module owns three related rules, all mirrored by the backend
 * normalizer in ``backend/app/services/tenant/documents_spreadsheet.py``:
 *
 *   - **sanitize** — strip the characters Excel forbids in a sheet name
 *     (they are the same ones the formula grammar uses as delimiters) and
 *     cap the length at 31 so an xlsx export never has to rename a sheet.
 *   - **uniqueness** — case-insensitive, because a reference resolves
 *     case-insensitively (``=sheet2!A1`` finds ``Sheet2``).
 *   - **quoting** — a name that isn't a bare identifier (or that could be
 *     read as a cell reference) has to be written ``'My Sheet'!A1``.
 *
 * Pure functions only: no React, no Yjs, no DOM.
 */

export type SheetId = string;

/** A sheet's identity, without any of its content. */
export interface SheetMeta {
  id: SheetId;
  name: string;
}

/** Excel's per-workbook sheet-name limit; keeping it means an xlsx export
 *  never has to silently truncate or rename. */
export const MAX_SHEET_NAME_LENGTH = 31;

/** Upper bound on sheets per document. Not an Excel limit — a bound on
 *  how large one JSON snapshot can get, since the whole workbook is
 *  PATCHed as a single ``document.content`` blob. */
export const MAX_SHEETS = 64;

/** The first sheet of every workbook uses a fixed id so that two clients
 *  bootstrapping the same empty Y.Doc at the same time converge instead of
 *  each minting a sheet. */
export const DEFAULT_SHEET_ID: SheetId = "s1";

// Characters Excel rejects in a sheet name. ``'`` is legal inside a name
// but not at either edge (it's the quote character), handled below.
const FORBIDDEN_CHARS = /[[\]:*?/\\]/g;

// A name that can be written without quotes in a formula: identifier-ish,
// no leading digit or period.
// The high-range escape keeps non-ASCII names (accents, CJK) unquoted,
// matching the formula grammar's own Sheet token.
const BARE_NAME = /^[A-Za-z_\u007F-\uFFFF][A-Za-z0-9_.\u007F-\uFFFF]*$/;

// Names that are legal identifiers but would be read as something else.
const LOOKS_LIKE_CELL = /^\$?[A-Za-z]{1,3}\$?[1-9][0-9]*$/;
const LOOKS_LIKE_RC = /^[Rr][0-9]*[Cc][0-9]*$/;
const LOOKS_LIKE_BOOLEAN = /^(?:TRUE|FALSE)$/i;

/**
 * Coerce arbitrary text into a legal sheet name: drop the forbidden
 * characters, collapse whitespace runs to single spaces, trim (including
 * edge apostrophes), and cap the length. Returns ``""`` when nothing
 * usable is left — callers substitute a default rather than accepting it.
 */
export const sanitizeSheetName = (raw: string): string =>
  raw
    .replace(FORBIDDEN_CHARS, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^'+|'+$/g, "")
    .trim()
    .slice(0, MAX_SHEET_NAME_LENGTH)
    // Slicing can re-expose a trailing space or quote.
    .replace(/['\s]+$/, "");

/** Case-insensitive identity key — how a formula resolves a sheet name. */
export const sheetNameKey = (name: string): string => name.trim().toLowerCase();

/**
 * ``desired``, or ``desired 2`` / ``desired 3`` / … until it no longer
 * collides (case-insensitively) with ``taken``. The numeric suffix is
 * trimmed into the length cap rather than pushing the name over it.
 */
export const uniqueSheetName = (desired: string, taken: Iterable<string>): string => {
  const used = new Set<string>();
  for (const name of taken) used.add(sheetNameKey(name));
  const base = sanitizeSheetName(desired) || "Sheet";
  if (!used.has(sheetNameKey(base))) return base;
  for (let n = 2; ; n++) {
    const suffix = ` ${n}`;
    const candidate = `${base.slice(0, MAX_SHEET_NAME_LENGTH - suffix.length).trim()}${suffix}`;
    if (!used.has(sheetNameKey(candidate))) return candidate;
  }
};

/** The next free ``Sheet<n>`` name for a workbook that already has
 *  ``taken`` — the label a freshly added tab gets. */
export const nextSheetName = (taken: Iterable<string>): string => {
  const used = new Set<string>();
  for (const name of taken) used.add(sheetNameKey(name));
  for (let n = 1; ; n++) {
    const candidate = `Sheet${n}`;
    if (!used.has(sheetNameKey(candidate))) return candidate;
  }
};

/** Whether a cross-sheet reference to ``name`` has to quote it. */
export const needsSheetQuoting = (name: string): boolean =>
  !BARE_NAME.test(name) ||
  LOOKS_LIKE_CELL.test(name) ||
  LOOKS_LIKE_RC.test(name) ||
  LOOKS_LIKE_BOOLEAN.test(name);

/** The sheet name as it appears inside a formula, quoted if it has to be
 *  (``Sheet2`` → ``Sheet2``; ``Q1 Actuals`` → ``'Q1 Actuals'``). */
export const quoteSheetName = (name: string): string =>
  needsSheetQuoting(name) ? `'${name.replace(/'/g, "''")}'` : name;

/** The full reference prefix, including the ``!`` (``'Q1 Actuals'!``). */
export const formatSheetPrefix = (name: string): string => `${quoteSheetName(name)}!`;

/** Inverse of {@link quoteSheetName}: the name a formula prefix spells. */
export const unquoteSheetName = (text: string): string =>
  text.startsWith("'") && text.endsWith("'") && text.length >= 2
    ? text.slice(1, -1).replace(/''/g, "'")
    : text;

/** Mint a sheet id. Random rather than sequential so two peers adding a
 *  sheet at the same moment never collide on one. */
export const newSheetId = (): SheetId => {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `s${uuid.replace(/-/g, "").slice(0, 12)}`;
  return `s${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-4)}`;
};
