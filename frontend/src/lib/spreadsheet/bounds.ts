/**
 * Where a sheet ends, and how you move around inside it.
 *
 * A sheet has three extents, and conflating them is how a cursor ends up on
 * a cell that isn't rendered, or a paste writes where nothing can ever show
 * it:
 *
 * - **the ceiling** ({@link CEILING}) — the hard maximum a workbook may
 *   reach. The backend normalizer enforces the same numbers and drops
 *   anything past them, so a write beyond here is a write that disappears.
 * - **the canvas** ({@link SheetBounds}) — how far the grid currently
 *   renders. Grows as data or scrolling reaches its edge, never past the
 *   ceiling.
 * - **the used range** ({@link usedRange}) — what is actually occupied.
 *   Drives "go to the end of the data" navigation and any operation that
 *   wants the real extent rather than the canvas.
 *
 * {@link sheetGrid} bundles the canvas with the other facts about which
 * cells exist — today, which rows and columns are hidden — and answers the
 * four questions the editor keeps asking: normalize a selection, walk a
 * range, step one cell, and list what to render. Every one of those has to
 * change when a cell can span more than one coordinate, so they live behind
 * one object rather than as loops written out at each call site.
 */

import { type CellRange, type CellValue, keyOf, normalizeRange, parseKey } from "./coords";

export const DEFAULT_ROWS = 100;
export const DEFAULT_COLS = 26;

/** The hard ceiling, matching the backend normalizer. */
export const MAX_ROWS = 100_000;
export const MAX_COLS = 1_000;

/** How far a sheet's grid currently extends. */
export interface SheetBounds {
  rows: number;
  cols: number;
}

export const CEILING: SheetBounds = { rows: MAX_ROWS, cols: MAX_COLS };

/** A cell coordinate. */
export interface CellPos {
  row: number;
  col: number;
}

/** The rectangle a sparse cell map actually occupies, or ``null`` when it
 *  holds nothing. Unlike ``boundingBox`` this is a range, not a size, so it
 *  says where the data *starts* as well as where it ends. */
export const usedRange = (
  cells: ReadonlyMap<string, CellValue> | Record<string, CellValue>
): CellRange | null => {
  let r1 = Number.POSITIVE_INFINITY;
  let c1 = Number.POSITIVE_INFINITY;
  let r2 = -1;
  let c2 = -1;
  const keys = cells instanceof Map ? cells.keys() : Object.keys(cells);
  for (const key of keys) {
    const parsed = parseKey(key);
    if (!parsed) continue;
    const [row, col] = parsed;
    if (row < r1) r1 = row;
    if (col < c1) c1 = col;
    if (row > r2) r2 = row;
    if (col > c2) c2 = col;
  }
  return r2 < 0 ? null : { r1, c1, r2, c2 };
};

/**
 * Split a block of writes into what fits under the ceiling and how much
 * didn't. Cells past it can't be rendered and don't survive a save, so a
 * caller reports the drop rather than writing them into the dark.
 */
export const clipToCeiling = (
  cells: Record<string, CellValue>,
  ceiling: SheetBounds = CEILING
): { kept: Record<string, CellValue>; dropped: number } => {
  const kept: Record<string, CellValue> = {};
  let dropped = 0;
  for (const [key, value] of Object.entries(cells)) {
    const parsed = parseKey(key);
    if (!parsed) continue;
    const [row, col] = parsed;
    if (row >= ceiling.rows || col >= ceiling.cols) {
      dropped++;
      continue;
    }
    kept[keyOf(row, col)] = value;
  }
  return { kept, dropped };
};

/** What a sheet's grid is shaped like: how far it extends, and which lines
 *  it draws at zero size. Merged cells join this when they land — which is
 *  why every traversal below goes through {@link sheetGrid} rather than
 *  being written out at its call site. */
export interface SheetShape {
  bounds: SheetBounds;
  isRowHidden?: (row: number) => boolean;
  isColHidden?: (col: number) => boolean;
}

/** One rendered cell's position and size within the grid body. */
export interface PlacedCell extends CellPos {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** A virtualized line: its index and its offset along the axis. */
export interface WindowLine {
  index: number;
  start: number;
}

export interface SheetGrid {
  bounds: SheetBounds;
  /** Pull a coordinate inside the canvas. */
  clampCell: (pos: CellPos) => CellPos;
  /** Pull a range's corners inside the canvas. When a cell can span more
   *  than one coordinate this is also where "never cut one in half" lands. */
  clampRange: (range: CellRange) => CellRange;
  /** The effective selection for a drag from ``anchor`` to ``focus``. The
   *  identity of the two corners today; a superset once a partly-covered
   *  span has to be swallowed whole. */
  normalizeSelection: (anchor: CellPos, focus: CellPos) => CellRange;
  /** Visit every cell of a range that holds a value in its own right. */
  forEachCell: (range: CellRange, visit: (row: number, col: number) => void) => void;
  /** One step from ``pos``, skipping over lines that aren't drawn. A step
   *  that would leave the canvas stays put. */
  step: (pos: CellPos, dRow: number, dCol: number) => CellPos;
  /** What to paint for a visible window, given each axis's virtualized
   *  lines and the size of a line. */
  cellsInWindow: (
    rows: readonly WindowLine[],
    cols: readonly WindowLine[],
    size: { width: (col: number) => number; height: (row: number) => number }
  ) => PlacedCell[];
}

const clampIndex = (value: number, limit: number): number =>
  Math.max(0, Math.min(Math.trunc(value), limit - 1));

export const sheetGrid = (shape: SheetShape): SheetGrid => {
  const { bounds } = shape;
  const rowHidden = shape.isRowHidden ?? (() => false);
  const colHidden = shape.isColHidden ?? (() => false);

  const clampCell = ({ row, col }: CellPos): CellPos => ({
    row: clampIndex(row, bounds.rows),
    col: clampIndex(col, bounds.cols),
  });

  const clampRange = (range: CellRange): CellRange => ({
    r1: clampIndex(range.r1, bounds.rows),
    c1: clampIndex(range.c1, bounds.cols),
    r2: clampIndex(range.r2, bounds.rows),
    c2: clampIndex(range.c2, bounds.cols),
  });

  // Walk one axis until a line that is actually drawn turns up. A run of
  // hidden lines is stepped over in one move; running out of drawn lines
  // leaves the position where it was, so the cursor never lands on
  // something invisible and never falls off the end.
  const stepAxis = (
    from: number,
    delta: number,
    limit: number,
    hidden: (i: number) => boolean
  ): number => {
    if (delta === 0) return from;
    const direction = Math.sign(delta);
    let remaining = Math.abs(delta);
    let at = from;
    while (remaining > 0) {
      let next = at + direction;
      while (next >= 0 && next < limit && hidden(next)) next += direction;
      if (next < 0 || next >= limit) break;
      at = next;
      remaining--;
    }
    return at;
  };

  return {
    bounds,
    clampCell,
    clampRange,
    normalizeSelection: (anchor, focus) => clampRange(normalizeRange(anchor, focus)),
    forEachCell: (range, visit) => {
      const { r1, c1, r2, c2 } = range;
      for (let r = r1; r <= r2; r++) {
        for (let c = c1; c <= c2; c++) visit(r, c);
      }
    },
    step: ({ row, col }, dRow, dCol) => ({
      row: stepAxis(clampIndex(row, bounds.rows), dRow, bounds.rows, rowHidden),
      col: stepAxis(clampIndex(col, bounds.cols), dCol, bounds.cols, colHidden),
    }),
    cellsInWindow: (rows, cols, size) => {
      const out: PlacedCell[] = [];
      for (const row of rows) {
        if (rowHidden(row.index)) continue;
        for (const col of cols) {
          if (colHidden(col.index)) continue;
          out.push({
            row: row.index,
            col: col.index,
            left: col.start,
            top: row.start,
            width: size.width(col.index),
            height: size.height(row.index),
          });
        }
      }
      return out;
    },
  };
};
