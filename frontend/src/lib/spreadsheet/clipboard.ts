/**
 * The spreadsheet clipboard: one representation for copy and cut alike.
 *
 * The OS clipboard can only carry text, and the text a spreadsheet writes is
 * computed values — that is what makes a copied block paste usefully into a
 * mail or a chat. But it is lossy: a formula arrives as the number it
 * happened to evaluate to, and formatting doesn't arrive at all. So a
 * {@link Clip} keeps the block as it really is — raw cells, formulas
 * included, with their formatting — alongside the exact text handed to the
 * OS. A paste compares the incoming text against that copy: if they match,
 * the clipboard still holds our block and the rich version is used; if they
 * differ, the user copied something else somewhere else and the text is
 * parsed as ordinary data.
 *
 * Copy and cut differ in exactly one way, and it's the way Excel differs:
 *
 * - **copy** translates relative references by how far the block moved, so
 *   a column of ``=A1*2`` pasted three rows down reads ``=A4*2``. ``$``
 *   pins, as everywhere else.
 * - **cut** is a move: references are kept verbatim, because the formula
 *   should go on meaning what it meant. Crossing sheets, "verbatim" needs
 *   help — an unqualified reference means "this sheet", which is a
 *   different sheet after the move — so those are qualified to the sheet
 *   the block came from.
 *
 * Pure module: the caller reads cells through the accessors it supplies and
 * applies the returned writes inside its own transaction.
 */

import {
  type CellRange,
  type CellValue,
  keyOf,
  parseKey,
  rangeSize,
} from "@/lib/spreadsheet/coords";
import {
  isFormula,
  qualifyLocalReferences,
  translateFormula,
} from "@/lib/spreadsheet/formula-refs";
import type { SheetId } from "@/lib/spreadsheet/sheets";
import type { CellFmt } from "@/lib/spreadsheet/styles";

export type ClipMode = "copy" | "cut";

export interface Clip {
  mode: ClipMode;
  /** The sheet the block came from, so a cut still knows what to clear and
   *  which sheet its unqualified references belong to after a tab switch. */
  sheetId: SheetId;
  /** That sheet's name at the time of the copy — what a qualified
   *  reference has to spell. */
  sheetName: string;
  /** Where it came from, in the source sheet's coordinates. */
  origin: CellRange;
  /** Raw cell values keyed by offset from the block's top-left, so
   *  ``"0:0"`` is the top-left cell whatever ``origin`` is. */
  cells: Record<string, CellValue>;
  /** Per-cell formatting under the same offset keys. */
  styles: Record<string, CellFmt>;
  /** Merged spans inside the block, in offset coordinates. Always empty
   *  today; merges are a declared future feature and this is where they
   *  will travel. */
  merges: CellRange[];
  /** Exactly what was written to the OS clipboard. A paste uses it to tell
   *  whether the clipboard still holds this block. */
  text: string;
}

/** How a clip reads the sheet it is being taken from. */
export interface ClipReader {
  /** The stored value — a formula stays ``"=..."``. */
  raw: (row: number, col: number) => CellValue;
  /** The formatting that cell carries in its own right. */
  style: (row: number, col: number) => CellFmt | undefined;
  /** What the cell shows — a formula's computed value or error token. This
   *  is what leaves for the OS clipboard. */
  display: (row: number, col: number) => CellValue;
}

const offsetKey = (row: number, col: number, origin: CellRange): string =>
  keyOf(row - origin.r1, col - origin.c1);

/** Serialize a rectangle to TSV of displayed values — the convention every
 *  other spreadsheet writes and reads. */
export const rangeToTsv = (range: CellRange, display: ClipReader["display"]): string => {
  const lines: string[] = [];
  for (let r = range.r1; r <= range.r2; r++) {
    const cols: string[] = [];
    for (let c = range.c1; c <= range.c2; c++) {
      const value = display(r, c);
      cols.push(value == null ? "" : String(value));
    }
    lines.push(cols.join("\t"));
  }
  return lines.join("\n");
};

export const clipFromSelection = (
  mode: ClipMode,
  source: { sheetId: SheetId; sheetName: string; range: CellRange },
  read: ClipReader
): Clip => {
  const { range } = source;
  const cells: Record<string, CellValue> = {};
  const styles: Record<string, CellFmt> = {};
  for (let r = range.r1; r <= range.r2; r++) {
    for (let c = range.c1; c <= range.c2; c++) {
      const key = offsetKey(r, c, range);
      const value = read.raw(r, c);
      if (value != null) cells[key] = value;
      const style = read.style(r, c);
      if (style && Object.keys(style).length > 0) styles[key] = style;
    }
  }
  return {
    mode,
    sheetId: source.sheetId,
    sheetName: source.sheetName,
    origin: range,
    cells,
    styles,
    merges: [],
    text: rangeToTsv(range, read.display),
  };
};

/** What pasting a clip does to the workbook. */
export interface Placement {
  /** Cell writes on the target sheet, keyed by absolute ``"r:c"``. */
  cells: Record<string, CellValue>;
  /** Formatting writes on the target sheet, same keys. */
  styles: Record<string, CellFmt>;
  /** Keys to clear on {@link Clip.sheetId} — a cut's source. Empty for a
   *  copy. */
  clear: string[];
  /** The rectangle the block now occupies on the target sheet. */
  target: CellRange;
  /** Structural changes the paste implies. Always empty today; merges
   *  land here. */
  structure: never[];
}

/**
 * Work out what pasting ``clip`` at ``at`` writes.
 *
 * ``at`` is the top-left of the destination. A cut also reports the source
 * keys to clear, and the caller is expected to apply both halves in one
 * transaction so the move is a single undo step.
 */
export const placeClip = (
  clip: Clip,
  at: { sheetId: SheetId; row: number; col: number }
): Placement => {
  const { rows, cols } = rangeSize(clip.origin);
  const rowDelta = at.row - clip.origin.r1;
  const colDelta = at.col - clip.origin.c1;
  const crossesSheets = at.sheetId !== clip.sheetId;

  const cells: Record<string, CellValue> = {};
  for (const [key, value] of Object.entries(clip.cells)) {
    const parsed = parseKey(key);
    if (!parsed) continue;
    cells[keyOf(at.row + parsed[0], at.col + parsed[1])] = moveValue(
      value,
      clip.mode,
      { rowDelta, colDelta },
      crossesSheets ? clip.sheetName : null
    );
  }

  const styles: Record<string, CellFmt> = {};
  for (const [key, style] of Object.entries(clip.styles)) {
    const parsed = parseKey(key);
    if (!parsed) continue;
    styles[keyOf(at.row + parsed[0], at.col + parsed[1])] = style;
  }

  const clear: string[] = [];
  if (clip.mode === "cut") {
    for (let r = clip.origin.r1; r <= clip.origin.r2; r++) {
      for (let c = clip.origin.c1; c <= clip.origin.c2; c++) clear.push(keyOf(r, c));
    }
  }

  return {
    cells,
    styles,
    clear,
    target: { r1: at.row, c1: at.col, r2: at.row + rows - 1, c2: at.col + cols - 1 },
    structure: [],
  };
};

const moveValue = (
  value: CellValue,
  mode: ClipMode,
  delta: { rowDelta: number; colDelta: number },
  qualifyWith: string | null
): CellValue => {
  if (!isFormula(value)) return value;
  // A copy re-points its relative references at the same *relative* cells.
  if (mode === "copy") return translateFormula(value, delta.rowDelta, delta.colDelta);
  // A move keeps them pointing at the same actual cells — which, landing on
  // another sheet, means saying which sheet that was.
  return qualifyWith === null ? value : qualifyLocalReferences(value, qualifyWith);
};

/** Whether the OS clipboard still holds what this clip wrote to it. A cut
 *  is answered on the clip alone: its marquee is the promise, and a failed
 *  or unavailable clipboard write must not turn a move into a copy. */
export const clipMatchesClipboard = (clip: Clip | null, text: string): clip is Clip => {
  if (!clip) return false;
  if (clip.mode === "cut") return true;
  return clip.text === text;
};
