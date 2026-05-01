/**
 * CSV serialization and parsing for spreadsheet cells.
 *
 * Export walks the cell map's bounding box row-major, emitting RFC
 * 4180-compliant fields. Import wraps papaparse, which already handles
 * quoted fields, embedded commas, escaped quotes, and CRLF / LF line
 * endings.
 */

import Papa from "papaparse";

import { boundingBox, keyOf, parseKey, type CellValue } from "./coords";

/**
 * Serialize a cell map to CSV text.
 *
 * Empty cells inside the bounding box become empty fields. Booleans
 * round-trip as the strings "true" / "false" (the same convention
 * Numbers / Excel use when interpreting CSV booleans on import).
 */
export const cellsToCsv = (
  cells: Record<string, CellValue> | ReadonlyMap<string, CellValue>
): string => {
  const lookup =
    cells instanceof Map
      ? (key: string) => cells.get(key)
      : (key: string) => (cells as Record<string, CellValue>)[key];
  const { rows, cols } = boundingBox(cells);
  if (rows === 0 || cols === 0) return "";
  const grid: string[][] = [];
  for (let r = 0; r < rows; r++) {
    const row: string[] = [];
    for (let c = 0; c < cols; c++) {
      const value = lookup(keyOf(r, c));
      row.push(value == null ? "" : String(value));
    }
    grid.push(row);
  }
  return Papa.unparse(grid, { newline: "\n" });
};

/**
 * Parse CSV / TSV text into a sparse cell map.
 *
 * Numbers are coerced to ``number``; the literal strings "true" /
 * "false" (case-insensitive) become booleans. Everything else stays a
 * string. Empty cells are not written to the map.
 */
export const csvToCells = (
  text: string,
  options: { delimiter?: string } = {}
): { cells: Record<string, CellValue>; rows: number; cols: number } => {
  const result = Papa.parse<string[]>(text, {
    delimiter: options.delimiter ?? "",
    skipEmptyLines: false,
    dynamicTyping: false,
  });

  const cells: Record<string, CellValue> = {};
  let rows = 0;
  let cols = 0;
  for (let r = 0; r < result.data.length; r++) {
    const row = result.data[r];
    if (!Array.isArray(row)) continue;
    for (let c = 0; c < row.length; c++) {
      const raw = row[c];
      if (raw === undefined || raw === "") continue;
      cells[keyOf(r, c)] = coerceScalar(raw);
      if (r + 1 > rows) rows = r + 1;
      if (c + 1 > cols) cols = c + 1;
    }
  }
  return { cells, rows, cols };
};

/**
 * Coerce a single text input from the user (or the clipboard, or a CSV
 * cell) to a scalar. Mirrors the heuristic the inline editor uses so
 * paste and direct typing produce the same shape.
 */
export const coerceScalar = (raw: string): CellValue => {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  const lower = trimmed.toLowerCase();
  if (lower === "true") return true;
  if (lower === "false") return false;
  // Numeric coercion: must look entirely numeric (allow ., -, e/E for
  // exponent notation) and round-trip cleanly. Don't coerce things
  // like "01234" since those usually are IDs / phone numbers, not
  // numbers — preserving the leading zero matters.
  if (/^-?\d+(\.\d+)?([eE][-+]?\d+)?$/.test(trimmed)) {
    if (trimmed.startsWith("0") && !trimmed.startsWith("0.") && trimmed !== "0") {
      return raw;
    }
    const num = Number(trimmed);
    if (Number.isFinite(num)) return num;
  }
  return raw;
};

/**
 * Pick the most likely delimiter for clipboard text. Papaparse can
 * sniff but defaulting to TSV when tabs are present matches what
 * Numbers / Excel write when you copy a multi-cell range.
 */
export const detectClipboardDelimiter = (text: string): string => {
  if (text.includes("\t")) return "\t";
  if (text.includes(",")) return ",";
  return "";
};

/**
 * Apply a parsed cell map starting at an origin offset. Used by the
 * paste handler so a 3×3 clipboard block dropped at B2 lands at B2:D4
 * rather than A1:C3.
 */
export const offsetCells = (
  cells: Record<string, CellValue>,
  originRow: number,
  originCol: number
): Record<string, CellValue> => {
  const out: Record<string, CellValue> = {};
  for (const [key, value] of Object.entries(cells)) {
    const parsed = parseKey(key);
    if (!parsed) continue;
    out[keyOf(parsed[0] + originRow, parsed[1] + originCol)] = value;
  }
  return out;
};
