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
