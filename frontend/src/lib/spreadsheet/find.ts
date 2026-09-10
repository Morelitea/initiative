/**
 * Find and replace over a sheet's cells.
 *
 * Searching looks at what is *stored*, not what is shown: a cell holding
 * ``=A1&" total"`` matches "total", and a cell computing ``42`` from
 * ``=40+2`` does not match "42". That is Excel's default ("look in:
 * formulas") and it is the only version where replace makes sense — you
 * replace the text you searched for, and a computed value has no text to
 * replace.
 *
 * Matching is plain substring work rather than a pattern language: a query
 * is what the user typed, so a stray ``.`` or ``(`` must match itself.
 *
 * Pure module — the caller supplies the cells and applies the writes.
 */

import { type CellValue, keyOf, parseKey } from "@/lib/spreadsheet/coords";

export interface FindOptions {
  matchCase: boolean;
  /** The query has to be the cell's whole contents, not a part of it. */
  wholeCell: boolean;
}

export interface CellMatch {
  row: number;
  col: number;
}

const asText = (value: CellValue): string => (value == null ? "" : String(value));

const matches = (text: string, query: string, options: FindOptions): boolean => {
  if (query === "") return false;
  const haystack = options.matchCase ? text : text.toLowerCase();
  const needle = options.matchCase ? query : query.toLowerCase();
  return options.wholeCell ? haystack === needle : haystack.includes(needle);
};

/**
 * Every matching cell, in reading order (top to bottom, left to right)
 * so "next match" walks the sheet the way the eye does.
 */
export const findInCells = (
  cells: ReadonlyMap<string, CellValue>,
  query: string,
  options: FindOptions
): CellMatch[] => {
  const found: CellMatch[] = [];
  if (query === "") return found;
  for (const [key, value] of cells) {
    const at = parseKey(key);
    if (!at) continue;
    if (matches(asText(value), query, options)) found.push({ row: at[0], col: at[1] });
  }
  found.sort((a, b) => a.row - b.row || a.col - b.col);
  return found;
};

/**
 * What a replace would write into ``value``, or ``null`` when it doesn't
 * match and the cell should be left exactly as it is. Every occurrence
 * inside the cell is replaced, which is what Excel's Replace does.
 *
 * The result is returned as text; the caller decides whether to re-coerce
 * it to a number or a boolean, because that is a spreadsheet-wide
 * convention rather than a search concern.
 */
export const replaceInValue = (
  value: CellValue,
  query: string,
  replacement: string,
  options: FindOptions
): string | null => {
  const text = asText(value);
  if (!matches(text, query, options)) return null;
  if (options.wholeCell) return replacement;

  const haystack = options.matchCase ? text : text.toLowerCase();
  const needle = options.matchCase ? query : query.toLowerCase();
  let out = "";
  let at = 0;
  for (;;) {
    const hit = haystack.indexOf(needle, at);
    if (hit < 0) break;
    out += text.slice(at, hit) + replacement;
    at = hit + needle.length;
  }
  return out + text.slice(at);
};

/** Every write a "replace all" would make, keyed by ``"r:c"``. */
export const replaceAllInCells = (
  cells: ReadonlyMap<string, CellValue>,
  query: string,
  replacement: string,
  options: FindOptions,
  coerce: (text: string) => CellValue
): Record<string, CellValue> => {
  const writes: Record<string, CellValue> = {};
  if (query === "") return writes;
  for (const [key, value] of cells) {
    const at = parseKey(key);
    if (!at) continue;
    const next = replaceInValue(value, query, replacement, options);
    if (next === null) continue;
    writes[keyOf(at[0], at[1])] = next === "" ? null : coerce(next);
  }
  return writes;
};
