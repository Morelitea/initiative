/**
 * Coordinate utilities for spreadsheet cells.
 *
 * Storage uses ``"r:c"`` integer-pair keys; the UI displays A1-style
 * column letters (A, B, … Z, AA, AB, …). All conversion math lives
 * here so the rest of the editor doesn't have to know about either
 * representation.
 */

export type CellKey = `${number}:${number}`;

export type CellValue = string | number | boolean | null;

export const keyOf = (row: number, col: number): CellKey => `${row}:${col}` as CellKey;

export const parseKey = (key: string): [number, number] | null => {
  const match = /^(\d+):(\d+)$/.exec(key);
  if (!match) return null;
  return [Number(match[1]), Number(match[2])];
};

/**
 * 0-indexed column number to A1 letters: 0 → "A", 25 → "Z", 26 → "AA",
 * 51 → "AZ", 52 → "BA", 701 → "ZZ", 702 → "AAA".
 */
export const colIndexToLetter = (col: number): string => {
  if (col < 0 || !Number.isInteger(col)) return "";
  let n = col;
  let result = "";
  while (n >= 0) {
    result = String.fromCharCode(65 + (n % 26)) + result;
    n = Math.floor(n / 26) - 1;
  }
  return result;
};

/**
 * Inverse of colIndexToLetter. Case-insensitive.
 * Invalid input returns -1.
 */
export const letterToColIndex = (letters: string): number => {
  if (!letters) return -1;
  const upper = letters.toUpperCase();
  let total = 0;
  for (let i = 0; i < upper.length; i++) {
    const code = upper.charCodeAt(i);
    if (code < 65 || code > 90) return -1;
    total = total * 26 + (code - 64);
  }
  return total - 1;
};

/** A normalized 0-based cell box (top-left .. bottom-right, inclusive). */
export interface CellRange {
  r1: number;
  c1: number;
  r2: number;
  c2: number;
}

// A1 cell ref or ``ref:ref`` range, ``$`` anchors allowed and ignored.
const A1_RANGE = /^\s*\$?([A-Za-z]+)\$?(\d+)(?:\s*:\s*\$?([A-Za-z]+)\$?(\d+))?\s*$/;

/**
 * Parse an A1-style reference or range (``"B12"``, ``"a1:c3"``, ``"$A$1"``)
 * into a normalized 0-based box, or ``null`` when the text isn't a valid
 * reference. Drives the formula bar's name-box go-to navigation; ``$`` anchors
 * are accepted but carry no meaning for navigation. Endpoints are sorted so
 * ``C3:A1`` and ``A1:C3`` yield the same box.
 */
export const parseA1Range = (text: string): CellRange | null => {
  const m = A1_RANGE.exec(text);
  if (!m) return null;
  const c1 = letterToColIndex(m[1]);
  const r1 = Number(m[2]) - 1;
  if (c1 < 0 || r1 < 0) return null;
  if (m[3] === undefined) return { r1, c1, r2: r1, c2: c1 };
  const c2 = letterToColIndex(m[3]);
  const r2 = Number(m[4]) - 1;
  if (c2 < 0 || r2 < 0) return null;
  return {
    r1: Math.min(r1, r2),
    c1: Math.min(c1, c2),
    r2: Math.max(r1, r2),
    c2: Math.max(c1, c2),
  };
};

/**
 * Compute the bounding box (max row + 1, max col + 1) of a sparse cell
 * map. Returns ``{ rows: 0, cols: 0 }`` for an empty map.
 */
export const boundingBox = (
  cells: ReadonlyMap<string, CellValue> | Record<string, CellValue>
): { rows: number; cols: number } => {
  let maxRow = -1;
  let maxCol = -1;
  const iterate = (key: string) => {
    const parsed = parseKey(key);
    if (!parsed) return;
    if (parsed[0] > maxRow) maxRow = parsed[0];
    if (parsed[1] > maxCol) maxCol = parsed[1];
  };
  if (cells instanceof Map) {
    for (const key of cells.keys()) iterate(key);
  } else {
    for (const key of Object.keys(cells)) iterate(key);
  }
  return { rows: maxRow + 1, cols: maxCol + 1 };
};
