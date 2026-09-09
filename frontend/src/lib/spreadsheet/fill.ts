/**
 * Fill-handle logic: extend a source rectangle across a dragged range,
 * the way a spreadsheet's bottom-right fill handle does.
 *
 * Three behaviors, decided per source *line* (each column of a vertical
 * fill, each row of a horizontal one):
 *   - Formula cells translate their *relative* references by the drag
 *     offset (``$`` stays pinned) via {@link translateFormula}.
 *   - Numeric or ``text + trailing integer`` lines extrapolate as a series
 *     (1,2,3 → 4,5,6; ``Item 1`` → ``Item 2``).
 *   - Anything else (booleans, plain text, mixed lines) tiles verbatim.
 *
 * Pure module — no React, no I/O. The caller supplies a ``read`` accessor
 * and applies the returned writes inside its own transaction.
 */

import { type CellKey, type CellRange, type CellValue, keyOf } from "@/lib/spreadsheet/coords";
import { isFormula, translateFormula } from "@/lib/spreadsheet/formula-refs";

/** Reads a cell value, ``null`` for an empty cell. */
type CellReader = (row: number, col: number) => CellValue;

const TRAILING_INT = /^(.*?)(\d+)$/;

const parseTrailingInt = (s: string): { prefix: string; num: number; pad: number } | null => {
  const m = TRAILING_INT.exec(s);
  if (!m) return null;
  return { prefix: m[1], num: Number(m[2]), pad: m[2].length };
};

const formatInt = (n: number, pad: number): string => {
  const digits = String(Math.abs(n)).padStart(pad, "0");
  return n < 0 ? `-${digits}` : digits;
};

/**
 * Decimal places in a number's shortest base-10 form (``0.1`` → 1, ``2`` → 0),
 * clamped to 12 so an already noisy seed like ``0.30000000000000004`` reports a
 * sane precision instead of 17, letting {@link roundTo} scrub the noise rather
 * than propagate it.
 */
const decimalPlaces = (n: number): number => {
  if (!Number.isFinite(n)) return 0;
  const s = String(n);
  const e = s.indexOf("e");
  if (e >= 0) {
    const dot = s.indexOf(".");
    const mantissa = dot >= 0 ? e - dot - 1 : 0;
    return Math.min(12, Math.max(0, mantissa - Number(s.slice(e + 1))));
  }
  const dot = s.indexOf(".");
  return dot >= 0 ? Math.min(12, s.length - dot - 1) : 0;
};

/** Round to ``dp`` decimals via decimal-string round-trip, dropping IEEE-754 drift. */
const roundTo = (x: number, dp: number): number => Number(x.toFixed(dp));

/**
 * Build an extrapolator over the offset ``n`` from a source line's first
 * cell (``n = 0`` is that first cell, ``n = length`` the cell just past the
 * end, ``n = -1`` the cell just before it), or ``null`` when the line is not
 * a recognized series and the caller should tile instead. Formula lines
 * always return ``null`` — they are translated, never extrapolated.
 */
const detectSeries = (values: CellValue[]): ((n: number) => CellValue) | null => {
  if (values.length === 0) return null;
  if (values.some((v) => v == null || isFormula(v))) return null;
  const H = values.length;

  // Numeric arithmetic progression. A single number has step 0 → a plain
  // copy, matching a spreadsheet's default single-cell drag.
  if (values.every((v) => typeof v === "number")) {
    const nums = values as number[];
    const step = H >= 2 ? (nums[H - 1] - nums[0]) / (H - 1) : 0;
    // Round each term to the seeds' precision so accumulated float drift
    // (0.1, 0.2 → 0.30000000000000004) doesn't surface in the filled cells.
    // ``reduce`` rather than ``Math.max(...spread)`` so a huge source range
    // can't blow the argument-count / call-stack limit.
    const dp = nums.reduce((acc, v) => Math.max(acc, decimalPlaces(v)), 0);
    return (n) => roundTo(nums[0] + step * n, dp);
  }

  // Constant-prefix text with a trailing integer (``Item 1`` → ``Item 2``).
  // A single such cell increments by 1 per step.
  if (values.every((v) => typeof v === "string")) {
    const parsed = (values as string[]).map(parseTrailingInt);
    const first = parsed[0];
    if (first && parsed.every((p) => p !== null && p.prefix === first.prefix)) {
      const items = parsed as { prefix: string; num: number; pad: number }[];
      const step = H >= 2 ? (items[H - 1].num - items[0].num) / (H - 1) : 1;
      return (n) => `${first.prefix}${formatInt(Math.round(items[0].num + step * n), first.pad)}`;
    }
  }

  return null;
};

/**
 * Compute the cell writes that fill ``source`` across ``target`` (the
 * drag-extended rectangle that shares one pair of edges with ``source`` and
 * grew along exactly one axis). Only the *new* region is returned; source
 * cells are left untouched. A ``null`` value means "clear this cell" — the
 * caller deletes that key to keep the map sparse.
 */
export const computeFillWrites = (
  read: CellReader,
  source: CellRange,
  target: CellRange
): Map<CellKey, CellValue> => {
  const writes = new Map<CellKey, CellValue>();
  const H = source.r2 - source.r1 + 1;
  const W = source.c2 - source.c1 + 1;
  const vertical = target.r1 < source.r1 || target.r2 > source.r2;

  if (vertical) {
    for (let c = source.c1; c <= source.c2; c++) {
      const line: CellValue[] = [];
      for (let k = 0; k < H; k++) line.push(read(source.r1 + k, c));
      const series = detectSeries(line);
      for (let r = target.r1; r <= target.r2; r++) {
        if (r >= source.r1 && r <= source.r2) continue; // never overwrite source
        const n = r - source.r1;
        if (series) {
          writes.set(keyOf(r, c), series(n));
          continue;
        }
        const srcR = source.r1 + (((n % H) + H) % H);
        const v = read(srcR, c);
        writes.set(keyOf(r, c), isFormula(v) ? translateFormula(v, r - srcR, 0) : v);
      }
    }
    return writes;
  }

  for (let r = source.r1; r <= source.r2; r++) {
    const line: CellValue[] = [];
    for (let k = 0; k < W; k++) line.push(read(r, source.c1 + k));
    const series = detectSeries(line);
    for (let c = target.c1; c <= target.c2; c++) {
      if (c >= source.c1 && c <= source.c2) continue;
      const n = c - source.c1;
      if (series) {
        writes.set(keyOf(r, c), series(n));
        continue;
      }
      const srcC = source.c1 + (((n % W) + W) % W);
      const v = read(r, srcC);
      writes.set(keyOf(r, c), isFormula(v) ? translateFormula(v, 0, c - srcC) : v);
    }
  }
  return writes;
};

/**
 * Double-click target: extend ``source`` *down* to the last contiguous
 * non-empty row of the neighboring column (the column just left of the
 * source, falling back to the one just right). Returns ``source`` unchanged
 * when neither neighbor has data to follow.
 */
export const computeAutofillTarget = (
  read: CellReader,
  source: CellRange,
  dims: { rows: number; cols: number }
): CellRange => {
  const below = source.r2 + 1;
  const leftHasData = source.c1 - 1 >= 0 && below < dims.rows && read(below, source.c1 - 1) != null;
  const rightHasData =
    source.c2 + 1 < dims.cols && below < dims.rows && read(below, source.c2 + 1) != null;
  const neighborCol = leftHasData ? source.c1 - 1 : rightHasData ? source.c2 + 1 : null;
  if (neighborCol === null) return source;

  let last = source.r2;
  for (let r = below; r < dims.rows; r++) {
    if (read(r, neighborCol) == null) break;
    last = r;
  }
  return last === source.r2 ? source : { ...source, r2: last };
};
