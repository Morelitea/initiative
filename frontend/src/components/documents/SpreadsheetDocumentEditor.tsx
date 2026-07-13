import type { ProviderAwareness } from "@lexical/yjs";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  type ClipboardEvent,
  type CSSProperties,
  Fragment,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import * as Y from "yjs";

import { FormulaCellInput } from "@/components/documents/spreadsheet/FormulaCellInput";
import { SpreadsheetFormulaBar } from "@/components/documents/spreadsheet/SpreadsheetFormulaBar";
import {
  SpreadsheetToolbar,
  type ToolbarSelection,
} from "@/components/documents/spreadsheet/SpreadsheetToolbar";
import { useSpreadsheetAwareness } from "@/components/documents/spreadsheet/useSpreadsheetAwareness";
import { useSpreadsheetCells } from "@/components/documents/spreadsheet/useSpreadsheetCells";
import { useSpreadsheetFormatting } from "@/components/documents/spreadsheet/useSpreadsheetFormatting";
import { useSpreadsheetHistory } from "@/components/documents/spreadsheet/useSpreadsheetHistory";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { matchHistoryShortcut } from "@/hooks/useYjsHistory";
import { toast } from "@/lib/chesterToast";
import {
  type CellValue,
  colIndexToLetter,
  keyOf,
  parseA1Range,
  parseKey,
} from "@/lib/spreadsheet/coords";
import {
  coerceScalar,
  csvToCells,
  detectClipboardDelimiter,
  offsetCells,
} from "@/lib/spreadsheet/csv";
import { type Box, computeAutofillTarget, computeFillWrites } from "@/lib/spreadsheet/fill";
import { createEvaluator, isFormula } from "@/lib/spreadsheet/formula";
import {
  extractReferences,
  FORMULA_REF_COLORS,
  type FormulaRefToken,
  referenceInsertTarget,
} from "@/lib/spreadsheet/formula-refs";
import { type SortDirection, sortSheetByColumn } from "@/lib/spreadsheet/sort";
import {
  type CellFmt,
  type ColumnFmt,
  formatCellValue,
  MAX_COL_WIDTH,
  MAX_ROW_HEIGHT,
  MIN_COL_WIDTH,
  MIN_ROW_HEIGHT,
  negativeRendersRed,
  type RowFmt,
  resolveCellFormat,
  resolveCellStyle,
  type SpreadsheetFormatting,
  sanitizeFormatting,
  styleToCss,
} from "@/lib/spreadsheet/styles";
import { type LineAxis, type LineOp, transformSheet } from "@/lib/spreadsheet/transform";
import { cn } from "@/lib/utils";

export interface SpreadsheetContent {
  schema_version: 1 | 2;
  kind: "spreadsheet";
  dimensions: { rows: number; cols: number };
  cells: Record<string, CellValue>;
  columns?: Record<string, ColumnFmt>;
  rows?: Record<string, RowFmt>;
  cellStyles?: Record<string, CellFmt>;
  frozen?: { rows: number; cols: number };
}

interface SpreadsheetDocumentEditorProps {
  initialContent: SpreadsheetContent;
  onContentChange: (content: SpreadsheetContent) => void;
  documentTitle: string;
  readOnly: boolean;
  className?: string;
  /** When non-null, cells live in ``yDoc.getMap("cells")`` and edits
   *  broadcast to peers in real time. When null (collab disabled or
   *  not yet ready), the editor falls back to local component state
   *  with the same UX. */
  yDoc?: Y.Doc | null;
  /** Awareness handle from the same provider as ``yDoc``. Used to
   *  publish / observe selected-cell presence rings. */
  awareness?: ProviderAwareness | null;
  /** Local user (id + display name) for awareness state. */
  currentUser?: { id: number; name: string } | null;
}

const ROW_HEIGHT = 28;
const COL_WIDTH = 110;
const ROW_HEADER_WIDTH = 56;
const COL_HEADER_HEIGHT = 26;
const DEFAULT_ROWS = 100;
const DEFAULT_COLS = 26;
const GROW_THRESHOLD = 5;
const ROW_GROWTH_STEP = 50;
const COL_GROWTH_STEP = 10;
const MAX_ROWS = 100_000;
const MAX_COLS = 1_000;
const RESIZE_HANDLE = 5;

// Functions that aggregate a range — picking one from the toolbar with a
// multi-cell selection fills the range in automatically (AutoSum-style).
const AGGREGATE_FUNCTIONS = new Set(["SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA"]);

const sanitizeContent = (raw: SpreadsheetContent | undefined): SpreadsheetContent => {
  const cells = (raw?.cells ?? {}) as Record<string, CellValue>;
  const requestedRows = raw?.dimensions?.rows ?? DEFAULT_ROWS;
  const requestedCols = raw?.dimensions?.cols ?? DEFAULT_COLS;
  return {
    schema_version: 2,
    kind: "spreadsheet",
    dimensions: {
      rows: Math.min(Math.max(requestedRows, DEFAULT_ROWS), MAX_ROWS),
      cols: Math.min(Math.max(requestedCols, DEFAULT_COLS), MAX_COLS),
    },
    cells,
  };
};

interface DragState {
  kind: "col" | "row";
  index: number;
  size: number;
}

/** A formula-reference highlight on one cell: its color and which of its
 *  edges sit on the boundary of the reference's box (so the four edges of a
 *  range draw a single outline rather than a grid of boxes). */
interface RefHighlight {
  color: string;
  top: boolean;
  right: boolean;
  bottom: boolean;
  left: boolean;
}

/** Stable empty array for non-editing cells, so they don't get a fresh
 *  ``refTokens`` prop identity every render. */
const EMPTY_REF_TOKENS: FormulaRefToken[] = [];

export const SpreadsheetDocumentEditor = ({
  initialContent,
  onContentChange,
  documentTitle,
  readOnly,
  className,
  yDoc = null,
  awareness = null,
  currentUser = null,
}: SpreadsheetDocumentEditorProps) => {
  const { t } = useTranslation(["documents", "common"]);

  const sanitizedInitial = useMemo(() => sanitizeContent(initialContent), [initialContent]);
  const initialFormatting = useMemo<SpreadsheetFormatting>(
    () => sanitizeFormatting(initialContent),
    [initialContent]
  );

  // Always operate on a Y.Doc so the (battle-tested) collaborative code
  // path is the single path and undo/redo works even with collaboration
  // off. When the provider supplies a real doc we use it; otherwise an
  // in-memory fallback. Awareness intentionally stays on the real
  // ``yDoc`` (a fallback doc has no provider/peers).
  //
  // ``useState`` (not ``useMemo``) so the doc is created exactly once
  // per real mount and re-created if React 18 StrictMode remounts; the
  // cleanup destroys *only* the fallback doc (never the provider's
  // ``yDoc``, which the parent owns).
  const [fallbackDoc] = useState(() => new Y.Doc());
  useEffect(() => () => fallbackDoc.destroy(), [fallbackDoc]);
  const docForData = yDoc ?? fallbackDoc;

  const { cells, dimensions, setCell, setDimensions, bulkUpdate, replaceAll } = useSpreadsheetCells(
    {
      yDoc: docForData,
      initialCells: sanitizedInitial.cells,
      initialDimensions: sanitizedInitial.dimensions,
    }
  );
  const formatting = useSpreadsheetFormatting({
    yDoc: docForData,
    initial: initialFormatting,
  });
  const history = useSpreadsheetHistory(docForData);
  // Stable callbacks (memoized in the hook, keyed on the doc) — depend
  // on these rather than the per-render ``history`` object literal.
  const { undo: undoHistory, redo: redoHistory } = history;

  // ``anchor`` is where the selection started, ``focus`` is the active
  // cell (drives editing / keyboard / the toolbar's indicator state).
  // ``mode`` decides what formatting targets: a cell rectangle, whole
  // columns (header click), or whole rows.
  const [sel, setSel] = useState<{
    anchor: { row: number; col: number };
    focus: { row: number; col: number };
    mode: "range" | "columns" | "rows";
  }>({ anchor: { row: 0, col: 0 }, focus: { row: 0, col: 0 }, mode: "range" });
  const [editing, setEditing] = useState<{ row: number; col: number; draft: string } | null>(null);
  // A pending cut (Excel-style "move"): the source rectangle and a snapshot
  // of its raw cell payload (keyed by offset from the top-left, formulas
  // preserved). The source isn't cleared until the next paste consumes it,
  // so an un-pasted cut is non-destructive. ``cancelCut`` drops the marquee.
  const [cut, setCut] = useState<{
    box: { r1: number; r2: number; c1: number; c2: number };
    payload: Record<string, CellValue>;
  } | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  // Which header/cell drag is in progress (null = not dragging).
  const selectingRef = useRef<null | "range" | "columns" | "rows">(null);
  // Fill-handle drag: ``fillSourceRef`` is the rectangle captured when the
  // drag began, ``fillTargetRef`` the latest extended rectangle. Both live in
  // refs so the once-registered window ``mouseup`` listener reads current
  // values (never a stale closure, the same reason ``selectingRef`` is a ref).
  // ``fillPreview`` mirrors the target in state purely to drive the tint.
  const fillSourceRef = useRef<Box | null>(null);
  const fillTargetRef = useRef<Box | null>(null);
  const [fillPreview, setFillPreview] = useState<Box | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const editingInputRef = useRef<HTMLInputElement>(null);
  const formulaBarInputRef = useRef<HTMLInputElement>(null);
  // The editing surface point-mode reference insertion and caret restoration
  // target: the in-cell input or the formula-bar input, whichever last gained
  // focus. Both edit the same draft, so a formula can be built from either.
  const activeEditorRef = useRef<HTMLInputElement | null>(null);
  // Set when an edit is begun by focusing the formula bar, so the
  // begin-edit auto-focus effect doesn't yank focus down into the cell input.
  const focusBarOnEditRef = useRef(false);
  // Set when an edit ends via the keyboard (Enter/Tab/Escape) so focus
  // returns to the grid — otherwise it falls to <body> as the input
  // unmounts and type-to-edit on the next cell stops working. A blur
  // (click-away) leaves this false so focus stays where the user clicked.
  const refocusGridRef = useRef(false);
  // Point-mode (click/drag a cell into the formula being edited). The most
  // recently inserted reference: ``anchor`` is the cell it started on, ``span``
  // the draft range it currently occupies (so an extend re-splices over it).
  // Persists across the mouseup that ends a click — a later shift-click reads
  // it to extend into a range — and is cleared when the edit ends or the user
  // types (which invalidates the recorded span).
  const pointRefRef = useRef<{
    anchor: { row: number; col: number };
    span: { start: number; end: number };
  } | null>(null);
  // True only while the mouse button is held after a point-mode click, so a
  // hover (mouseenter) extends the range during a drag but not on a stray
  // pass-over. Cleared on mouseup (see the fill-drag listener).
  const pointDraggingRef = useRef(false);
  // Caret offset to restore after a point-mode splice updates the draft (the
  // input is controlled, so the selection must be reapplied post-render).
  const pendingCaretRef = useRef<number | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const resizeStartRef = useRef<{ pos: number; size: number }>({ pos: 0, size: 0 });
  // Owns the window listeners attached during a resize drag.  Held in a ref
  // so the unmount cleanup (below) can abort an in-flight drag, preventing
  // a stale formatting write after the editor has gone away.
  const resizeAbortRef = useRef<AbortController | null>(null);
  // Stable ref so the resize handler can call the latest formatting mutators
  // without listing `formatting` (a new object every render) as a dependency.
  const formattingRef = useRef(formatting);
  formattingRef.current = formatting; // keep current on every render

  // Effective per-index sizes: an in-flight resize preview wins over the
  // shared formatting value, which wins over the constant default.
  const colWidth = useCallback(
    (c: number): number => {
      if (drag?.kind === "col" && drag.index === c) return drag.size;
      return formatting.columns[String(c)]?.width ?? COL_WIDTH;
    },
    [drag, formatting.columns]
  );
  const rowHeight = useCallback(
    (r: number): number => {
      if (drag?.kind === "row" && drag.index === r) return drag.size;
      return formatting.rows[String(r)]?.height ?? ROW_HEIGHT;
    },
    [drag, formatting.rows]
  );

  // Stable refs the virtualizer's estimateSize reads, so its callback
  // identity never changes (a changing estimateSize fights the cache);
  // we explicitly ``measure()`` below when sizes actually change.
  const colWidthRef = useRef(colWidth);
  const rowHeightRef = useRef(rowHeight);
  useEffect(() => {
    colWidthRef.current = colWidth;
    rowHeightRef.current = rowHeight;
  }, [colWidth, rowHeight]);

  // Auto-grow dimensions when the cell map writes past the canvas.
  // Local-only — each peer converges on the same size from the shared
  // cell map without a Y.Map round-trip per write.
  useEffect(() => {
    let maxRow = -1;
    let maxCol = -1;
    for (const key of cells.keys()) {
      const colon = key.indexOf(":");
      if (colon < 0) continue;
      const r = Number(key.slice(0, colon));
      const c = Number(key.slice(colon + 1));
      if (r > maxRow) maxRow = r;
      if (c > maxCol) maxCol = c;
    }
    const nextRows = Math.min(Math.max(maxRow + 1, dimensions.rows), MAX_ROWS);
    const nextCols = Math.min(Math.max(maxCol + 1, dimensions.cols), MAX_COLS);
    if (nextRows !== dimensions.rows || nextCols !== dimensions.cols) {
      setDimensions({ rows: nextRows, cols: nextCols });
    }
  }, [cells, dimensions, setDimensions]);

  // Formula evaluator bound to the current cell snapshot. Rebuilt whenever
  // ``cells`` changes (local edit, remote peer write, undo/redo all yield a
  // fresh map), so computed values recalc automatically; each formula is
  // evaluated at most once per snapshot via the evaluator's internal cache,
  // and only for cells the virtualized grid actually renders.
  const evaluator = useMemo(() => createEvaluator(cells), [cells]);

  // References in the formula currently being edited, used to color the
  // editor text and outline the cells they point at. Empty unless a formula
  // (``=...``) is being typed.
  const editingRefs = useMemo<FormulaRefToken[]>(
    () => (editing && isFormula(editing.draft) ? extractReferences(editing.draft) : []),
    [editing]
  );

  // The reference highlight (color + which edges form the box boundary) for a
  // single cell, or null. Scans the (few) tokens rather than pre-enumerating
  // every cell of every range, so a huge ``A1:A100000`` stays cheap.
  const refHighlightAt = useCallback(
    (r: number, c: number): RefHighlight | null => {
      for (const t of editingRefs) {
        if (r >= t.r1 && r <= t.r2 && c >= t.c1 && c <= t.c2) {
          return {
            color: FORMULA_REF_COLORS[t.colorIndex % FORMULA_REF_COLORS.length],
            top: r === t.r1,
            bottom: r === t.r2,
            left: c === t.c1,
            right: c === t.c2,
          };
        }
      }
      return null;
    },
    [editingRefs]
  );

  // Emit the JSON snapshot to the parent on every change so the
  // existing autosave hook can PATCH ``document.content``. Captured in
  // a ref so callers can pass an inline arrow without thrashing this
  // effect into a setState loop.
  const onContentChangeRef = useRef(onContentChange);
  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);
  // Skip the on-mount run so opening a doc doesn't flip ``isDirty`` and
  // arm the autosave timer with no user interaction.
  const skipFirstEmitRef = useRef(true);
  useEffect(() => {
    if (skipFirstEmitRef.current) {
      skipFirstEmitRef.current = false;
      return;
    }
    const cellsObj: Record<string, CellValue> = {};
    for (const [key, value] of cells) cellsObj[key] = value;
    onContentChangeRef.current({
      schema_version: 2,
      kind: "spreadsheet",
      dimensions,
      cells: cellsObj,
      columns: formatting.columns,
      rows: formatting.rows,
      cellStyles: formatting.cellStyles,
      frozen: formatting.frozen,
    });
  }, [
    cells,
    dimensions,
    formatting.columns,
    formatting.rows,
    formatting.cellStyles,
    formatting.frozen,
  ]);

  const rowVirtualizer = useVirtualizer({
    count: dimensions.rows,
    getScrollElement: () => containerRef.current,
    estimateSize: (index) => rowHeightRef.current(index),
    overscan: 5,
  });

  const colVirtualizer = useVirtualizer({
    count: dimensions.cols,
    getScrollElement: () => containerRef.current,
    estimateSize: (index) => colWidthRef.current(index),
    horizontal: true,
    overscan: 3,
  });

  // Recompute virtual offsets when explicit sizes change (remote write,
  // local resize commit, or live drag preview). Without this the
  // virtualizer keeps stale cached sizes.
  useEffect(() => {
    rowVirtualizer.measure();
  }, [formatting.rows, drag, rowVirtualizer]);
  useEffect(() => {
    colVirtualizer.measure();
  }, [formatting.columns, drag, colVirtualizer]);

  // Auto-grow the canvas when scrolling near the edge so the grid feels
  // unbounded. Local: scroll position is a personal UX concern.
  const virtualRows = rowVirtualizer.getVirtualItems();
  const virtualCols = colVirtualizer.getVirtualItems();
  useEffect(() => {
    if (virtualRows.length === 0) return;
    const lastRow = virtualRows[virtualRows.length - 1].index;
    if (lastRow >= dimensions.rows - GROW_THRESHOLD && dimensions.rows < MAX_ROWS) {
      setDimensions({
        rows: Math.min(dimensions.rows + ROW_GROWTH_STEP, MAX_ROWS),
        cols: dimensions.cols,
      });
    }
  }, [virtualRows, dimensions, setDimensions]);
  useEffect(() => {
    if (virtualCols.length === 0) return;
    const lastCol = virtualCols[virtualCols.length - 1].index;
    if (lastCol >= dimensions.cols - GROW_THRESHOLD && dimensions.cols < MAX_COLS) {
      setDimensions({
        rows: dimensions.rows,
        cols: Math.min(dimensions.cols + COL_GROWTH_STEP, MAX_COLS),
      });
    }
  }, [virtualCols, dimensions, setDimensions]);

  const selBox = useMemo(() => {
    const r1 = Math.min(sel.anchor.row, sel.focus.row);
    const r2 = Math.max(sel.anchor.row, sel.focus.row);
    const c1 = Math.min(sel.anchor.col, sel.focus.col);
    const c2 = Math.max(sel.anchor.col, sel.focus.col);
    return { r1, r2, c1, c2 };
  }, [sel]);

  const isInSel = useCallback(
    (r: number, c: number): boolean => {
      const { r1, r2, c1, c2 } = selBox;
      if (sel.mode === "columns") return c >= c1 && c <= c2;
      if (sel.mode === "rows") return r >= r1 && r <= r2;
      return r >= r1 && r <= r2 && c >= c1 && c <= c2;
    },
    [sel.mode, selBox]
  );

  const colHeaderActive = useCallback(
    (c: number): boolean => sel.mode !== "rows" && c >= selBox.c1 && c <= selBox.c2,
    [sel.mode, selBox]
  );
  const rowHeaderActive = useCallback(
    (r: number): boolean => sel.mode !== "columns" && r >= selBox.r1 && r <= selBox.r2,
    [sel.mode, selBox]
  );

  // The contiguous band a header context-menu should act on: the active
  // multi-selection when the right-clicked header falls inside it (so
  // insert/delete operate on every selected line), otherwise just the
  // single clicked line.
  const lineBand = useCallback(
    (axis: LineAxis, index: number): { start: number; count: number } => {
      if (axis === "col" && sel.mode === "columns" && index >= selBox.c1 && index <= selBox.c2)
        return { start: selBox.c1, count: selBox.c2 - selBox.c1 + 1 };
      if (axis === "row" && sel.mode === "rows" && index >= selBox.r1 && index <= selBox.r2)
        return { start: selBox.r1, count: selBox.r2 - selBox.r1 + 1 };
      return { start: index, count: 1 };
    },
    [sel.mode, selBox]
  );

  const selectCell = useCallback((row: number, col: number, extend = false) => {
    setSel((p) =>
      extend
        ? { anchor: p.anchor, focus: { row, col }, mode: "range" }
        : { anchor: { row, col }, focus: { row, col }, mode: "range" }
    );
  }, []);

  const selectColumn = useCallback((col: number, extend = false) => {
    setSel((p) => ({
      anchor: extend && p.mode === "columns" ? p.anchor : { row: 0, col },
      focus: { row: 0, col },
      mode: "columns",
    }));
  }, []);

  const selectRow = useCallback((row: number, extend = false) => {
    setSel((p) => ({
      anchor: extend && p.mode === "rows" ? p.anchor : { row, col: 0 },
      focus: { row, col: 0 },
      mode: "rows",
    }));
  }, []);

  const moveSelection = useCallback((dRow: number, dCol: number, extend = false) => {
    setSel((p) => {
      const row = Math.max(0, Math.min(p.focus.row + dRow, MAX_ROWS - 1));
      const col = Math.max(0, Math.min(p.focus.col + dCol, MAX_COLS - 1));
      return extend
        ? { anchor: p.anchor, focus: { row, col }, mode: "range" }
        : { anchor: { row, col }, focus: { row, col }, mode: "range" };
    });
  }, []);

  // Name-box go-to: select the cell/range the text names (clamped to the grid)
  // and scroll its top-left into view. Invalid input is ignored — the name box
  // resets to the current selection on blur.
  const navigateToRef = useCallback(
    (text: string) => {
      const box = parseA1Range(text);
      if (!box) return;
      const r1 = Math.min(box.r1, dimensions.rows - 1);
      const c1 = Math.min(box.c1, dimensions.cols - 1);
      const r2 = Math.min(box.r2, dimensions.rows - 1);
      const c2 = Math.min(box.c2, dimensions.cols - 1);
      // Anchor at the bottom-right so the active (focus) cell is the top-left,
      // matching how a spreadsheet lands the cursor on a navigated range.
      setSel({ anchor: { row: r2, col: c2 }, focus: { row: r1, col: c1 }, mode: "range" });
      rowVirtualizer.scrollToIndex(r1, { align: "center" });
      colVirtualizer.scrollToIndex(c1, { align: "center" });
      containerRef.current?.focus();
    },
    [dimensions.rows, dimensions.cols, rowVirtualizer, colVirtualizer]
  );

  // Commit a fill (drag or double-click): tile / extrapolate the source
  // rectangle across the new region in one transaction, then keep the filled
  // block selected. A target identical to the source (a click with no drag)
  // is a no-op. ``null`` writes clear their cell so the map stays sparse.
  const commitFill = useCallback(
    (source: Box, target: Box) => {
      if (readOnly) return;
      const writes = computeFillWrites((r, c) => cells.get(keyOf(r, c)) ?? null, source, target);
      if (writes.size === 0) return;
      bulkUpdate((draft) => {
        for (const [key, value] of writes) {
          if (value == null) draft.delete(key);
          else draft.set(key, value);
        }
      });
      // Anchor on the target's top-left (not the source's) so an up/left
      // fill — where target.r1/c1 sit above/left of the source — keeps the
      // whole written region selected, not just the original cells.
      setSel({
        anchor: { row: target.r1, col: target.c1 },
        focus: { row: target.r2, col: target.c2 },
        mode: "range",
      });
    },
    [readOnly, cells, bulkUpdate]
  );
  // The once-registered window ``mouseup`` listener calls the latest commit
  // through this ref (its closure would otherwise capture a stale ``cells``).
  const commitFillRef = useRef(commitFill);
  commitFillRef.current = commitFill;

  // Grab the fill handle: capture the current selection as the source and
  // seed the preview there (a click with no drag stays a no-op).
  const startFill = useCallback(() => {
    if (readOnly) return;
    fillSourceRef.current = selBox;
    fillTargetRef.current = selBox;
    setFillPreview(selBox);
  }, [readOnly, selBox]);

  // Extend an in-progress fill toward a hovered cell, constrained to the
  // dominant axis (vertical vs horizontal), the way a fill handle is.
  const extendFill = useCallback((row: number, col: number) => {
    const source = fillSourceRef.current;
    if (!source) return;
    const vert = Math.max(0, row - source.r2, source.r1 - row);
    const horiz = Math.max(0, col - source.c2, source.c1 - col);
    let target: Box;
    if (vert === 0 && horiz === 0) target = source;
    else if (vert >= horiz)
      target = { ...source, r1: Math.min(source.r1, row), r2: Math.max(source.r2, row) };
    else target = { ...source, c1: Math.min(source.c1, col), c2: Math.max(source.c2, col) };
    fillTargetRef.current = target;
    setFillPreview(target);
  }, []);

  // Double-click the handle: fill down to the neighbor column's data extent.
  const autofillDown = useCallback(() => {
    if (readOnly) return;
    const target = computeAutofillTarget(
      (r, c) => cells.get(keyOf(r, c)) ?? null,
      selBox,
      dimensions
    );
    commitFill(selBox, target);
  }, [readOnly, cells, selBox, dimensions, commitFill]);

  // Clear the selectingRef on any pointer release so a drag that ends
  // off-grid still stops extending the selection. A fill drag commits here.
  useEffect(() => {
    const onUp = () => {
      selectingRef.current = null;
      // End any point-mode drag, but keep the last reference so a follow-up
      // shift-click can still extend it into a range.
      pointDraggingRef.current = false;
      const source = fillSourceRef.current;
      if (source) {
        const target = fillTargetRef.current ?? source;
        fillSourceRef.current = null;
        fillTargetRef.current = null;
        setFillPreview(null);
        commitFillRef.current(source, target);
      }
    };
    window.addEventListener("mouseup", onUp);
    return () => window.removeEventListener("mouseup", onUp);
  }, []);

  const { peerSelectionsByCell } = useSpreadsheetAwareness({
    awareness,
    clientId: yDoc?.clientID ?? null,
    user: currentUser,
    selected: sel.focus,
    enabled: Boolean(awareness && yDoc && currentUser),
    publishLocal: !readOnly,
  });

  const beginEdit = useCallback(
    (row: number, col: number, initialDraft?: string) => {
      if (readOnly) return;
      setCut(null); // starting an edit cancels a pending cut (Excel behavior)
      const existing = cells.get(keyOf(row, col));
      const initial =
        initialDraft !== undefined ? initialDraft : existing == null ? "" : String(existing);
      setEditing({ row, col, draft: initial });
    },
    [cells, readOnly]
  );

  const commitEdit = useCallback(
    (next?: { row: number; col: number }) => {
      if (!editing) return;
      const value = coerceScalar(editing.draft);
      setCell(editing.row, editing.col, value === "" ? null : value);
      setEditing(null);
      pointRefRef.current = null;
      if (next) selectCell(next.row, next.col);
    },
    [editing, setCell, selectCell]
  );

  const cancelEdit = useCallback(() => {
    setEditing(null);
    pointRefRef.current = null;
  }, []);

  // Blur handler shared by the in-cell input and the formula-bar input. A blur
  // that hands focus to the *other* editing surface is a surface switch, not
  // an edit end — keep the draft alive instead of committing.
  const handleEditorBlur = useCallback(
    (e: React.FocusEvent<HTMLInputElement>) => {
      const next = e.relatedTarget;
      if (next === formulaBarInputRef.current || next === editingInputRef.current) return;
      commitEdit();
    },
    [commitEdit]
  );

  // Point mode: splice the clicked cell's reference into the formula being
  // edited. ``extend`` builds an ``A1:B3`` range from the drag anchor and
  // overwrites the reference inserted on mousedown; otherwise it resolves the
  // caret position (insert vs replace-the-last-ref) and seeds the drag.
  // Returns false when the caret isn't in a reference-accepting spot, so the
  // caller falls back to a normal (committing) click.
  const insertReference = useCallback(
    (row: number, col: number, extend: boolean): boolean => {
      if (!editing) return false;
      const input = activeEditorRef.current ?? editingInputRef.current;
      if (!input) return false;
      const draft = editing.draft;
      const cellRef = (r: number, c: number) => `${colIndexToLetter(c)}${r + 1}`;
      let span: { start: number; end: number };
      let refText: string;
      if (extend) {
        const last = pointRefRef.current;
        if (!last) return false;
        span = last.span;
        const r1 = Math.min(last.anchor.row, row);
        const r2 = Math.max(last.anchor.row, row);
        const c1 = Math.min(last.anchor.col, col);
        const c2 = Math.max(last.anchor.col, col);
        refText =
          r1 === r2 && c1 === c2 ? cellRef(r1, c1) : `${cellRef(r1, c1)}:${cellRef(r2, c2)}`;
      } else {
        const caret = input.selectionStart ?? draft.length;
        const target = referenceInsertTarget(draft, caret);
        if (target.kind === "none") return false;
        span =
          target.kind === "insert"
            ? { start: target.at, end: target.at }
            : { start: target.start, end: target.end };
        refText = cellRef(row, col);
        pointRefRef.current = { anchor: { row, col }, span };
      }
      const next = draft.slice(0, span.start) + refText + draft.slice(span.end);
      const newEnd = span.start + refText.length;
      if (pointRefRef.current) pointRefRef.current.span = { start: span.start, end: newEnd };
      pendingCaretRef.current = newEnd;
      setEditing({ row: editing.row, col: editing.col, draft: next });
      return true;
    },
    [editing]
  );

  // Restore the caret after a point-mode splice (the controlled input resets
  // it on re-render). Runs before paint so there's no visible jump.
  useLayoutEffect(() => {
    if (pendingCaretRef.current === null) return;
    const input = activeEditorRef.current ?? editingInputRef.current;
    if (input) {
      const pos = pendingCaretRef.current;
      input.focus();
      input.setSelectionRange(pos, pos);
    }
    pendingCaretRef.current = null;
  }, [editing]);

  // Insert a formula from the toolbar's function menu. When an aggregate
  // (SUM/AVERAGE/…) is picked with a multi-cell range selected, drop a
  // completed ``=FN(range)`` in the cell just past the selection — below a
  // tall selection, to the right of a wide one — so the formula never sits
  // inside its own range (which would be a cycle). Otherwise begin editing
  // the focus cell with a ``=FN(`` starter so the user fills the arguments.
  const insertFunction = useCallback(
    (name: string) => {
      if (readOnly) return;
      const isAggregate = AGGREGATE_FUNCTIONS.has(name);
      const { r1, r2, c1, c2 } = selBox;
      const isRange = sel.mode === "range" && (r1 !== r2 || c1 !== c2);
      if (isAggregate && isRange) {
        const rangeRef = `${colIndexToLetter(c1)}${r1 + 1}:${colIndexToLetter(c2)}${r2 + 1}`;
        const vertical = r2 - r1 >= c2 - c1;
        // Clamp into the grid: a selection ending on the last row/column
        // would otherwise target a cell that never renders, silently
        // dropping the formula.
        const targetRow = vertical ? Math.min(r2 + 1, MAX_ROWS - 1) : r1;
        const targetCol = vertical ? c1 : Math.min(c2 + 1, MAX_COLS - 1);
        setCell(targetRow, targetCol, `=${name}(${rangeRef})`);
        selectCell(targetRow, targetCol);
        // Return focus to the grid so arrow keys work immediately (the menu
        // suppresses its own close-auto-focus so it can't fight this).
        containerRef.current?.focus();
        return;
      }
      // Begin editing the focus cell; the editing-input focus effect takes
      // over once the input mounts.
      beginEdit(sel.focus.row, sel.focus.col, `=${name}(`);
    },
    [readOnly, selBox, sel.mode, sel.focus, setCell, selectCell, beginEdit]
  );

  const editingCellKey = editing ? `${editing.row}:${editing.col}` : null;
  useEffect(() => {
    if (editingCellKey && editingInputRef.current) {
      // Edit begun from the formula bar: leave focus there (the cell input is
      // still mounted as a mirror, but the user is typing in the bar).
      if (focusBarOnEditRef.current) {
        focusBarOnEditRef.current = false;
        return;
      }
      activeEditorRef.current = editingInputRef.current;
      editingInputRef.current.focus();
    } else if (!editingCellKey && refocusGridRef.current) {
      // Edit ended via the keyboard: pull focus back to the grid (the
      // input has now unmounted) so the next keystroke is handled.
      refocusGridRef.current = false;
      containerRef.current?.focus();
    }
  }, [editingCellKey]);

  // Delete every cell value covered by the selection. For a range that's
  // the rectangle; for whole-column/row selections, only the cells that
  // actually hold data (the map is sparse) so a clear is bounded.
  const clearSelection = useCallback(() => {
    if (readOnly) return;
    setCut(null);
    const { r1, r2, c1, c2 } = selBox;
    bulkUpdate((draft) => {
      if (sel.mode === "range") {
        for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) draft.delete(keyOf(r, c));
        return;
      }
      for (const key of Array.from(draft.keys())) {
        const p = parseKey(key);
        if (!p) continue;
        const [r, c] = p;
        if (sel.mode === "columns" ? c >= c1 && c <= c2 : r >= r1 && r <= r2) {
          draft.delete(key);
        }
      }
    });
  }, [readOnly, sel.mode, selBox, bulkUpdate]);

  // Resolve a cell to the value that should leave the editor (copy / cut /
  // file export): a formula yields its computed result (or error token), a
  // literal yields itself. Keeps exported files and pastes as data, never
  // raw ``=...`` text whose relative refs wouldn't survive the move.
  const resolveExport = useCallback(
    (row: number, col: number): CellValue => {
      const v = cells.get(keyOf(row, col)) ?? null;
      if (!isFormula(v)) return v;
      const { value, error } = evaluator.evaluate(row, col);
      return error ?? value;
    },
    [cells, evaluator]
  );

  // Serialize the current selection to TSV of computed values, the
  // Sheets/Excel clipboard convention. Column/row selections serialize
  // just the focus cell (a whole column would be unbounded).
  const selectionToTsv = useCallback((): string => {
    if (sel.mode === "range") {
      const { r1, r2, c1, c2 } = selBox;
      const lines: string[] = [];
      for (let r = r1; r <= r2; r++) {
        const cols: string[] = [];
        for (let c = c1; c <= c2; c++) {
          const v = resolveExport(r, c);
          cols.push(v == null ? "" : String(v));
        }
        lines.push(cols.join("\t"));
      }
      return lines.join("\n");
    }
    const v = resolveExport(sel.focus.row, sel.focus.col);
    return v == null ? "" : String(v);
  }, [sel.mode, sel.focus, selBox, resolveExport]);

  // Cut = move. Snapshot the source rectangle's raw cells (formulas kept
  // verbatim) and mark it with a marquee; the source is only cleared when
  // a paste consumes the cut (see handlePaste). Also writes computed values
  // to the OS clipboard so the cut block can be pasted into other apps.
  // Driven from the keyboard (Ctrl/Cmd+X) because the browser doesn't fire
  // a native ``cut`` event on a non-editable grid.
  const handleCut = useCallback(() => {
    if (readOnly || editing) return;
    const box =
      sel.mode === "range"
        ? selBox
        : { r1: sel.focus.row, r2: sel.focus.row, c1: sel.focus.col, c2: sel.focus.col };
    const payload: Record<string, CellValue> = {};
    for (let r = box.r1; r <= box.r2; r++) {
      for (let c = box.c1; c <= box.c2; c++) {
        const v = cells.get(keyOf(r, c));
        if (v != null) payload[keyOf(r - box.r1, c - box.c1)] = v;
      }
    }
    const tsv = selectionToTsv();
    if (tsv) void navigator.clipboard?.writeText(tsv).catch(() => {});
    setCut({ box, payload });
  }, [readOnly, editing, sel.mode, sel.focus, selBox, cells, selectionToTsv]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (editing) return;
      if (readOnly) return;
      const histAction = matchHistoryShortcut(e);
      if (histAction) {
        e.preventDefault();
        if (histAction === "undo") undoHistory();
        else redoHistory();
        return;
      }
      // Cut (Ctrl/Cmd+X) — the grid div gets no native ``cut`` event, so we
      // drive it from the keyboard. Copy/paste still use the native events.
      if ((e.ctrlKey || e.metaKey) && (e.key === "x" || e.key === "X")) {
        e.preventDefault();
        handleCut();
        return;
      }
      const { row, col } = sel.focus;
      switch (e.key) {
        case "Escape":
          if (cut) {
            e.preventDefault();
            setCut(null);
          }
          return;
        case "ArrowDown":
          e.preventDefault();
          moveSelection(1, 0, e.shiftKey);
          return;
        case "ArrowUp":
          e.preventDefault();
          moveSelection(-1, 0, e.shiftKey);
          return;
        case "ArrowRight":
          e.preventDefault();
          moveSelection(0, 1, e.shiftKey);
          return;
        case "ArrowLeft":
          e.preventDefault();
          moveSelection(0, -1, e.shiftKey);
          return;
        case "Enter":
        case "F2":
          e.preventDefault();
          beginEdit(row, col);
          return;
        case "Backspace":
        case "Delete":
          e.preventDefault();
          clearSelection();
          return;
        case "Tab":
          e.preventDefault();
          moveSelection(0, e.shiftKey ? -1 : 1);
          return;
      }
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        beginEdit(row, col, e.key);
      }
    },
    [
      editing,
      readOnly,
      cut,
      handleCut,
      undoHistory,
      redoHistory,
      sel.focus,
      moveSelection,
      beginEdit,
      clearSelection,
    ]
  );

  const handleEditingKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (!editing) return;
      switch (e.key) {
        case "Enter":
          e.preventDefault();
          refocusGridRef.current = true;
          commitEdit({ row: editing.row + 1, col: editing.col });
          return;
        case "Escape":
          e.preventDefault();
          refocusGridRef.current = true;
          cancelEdit();
          return;
        case "Tab":
          e.preventDefault();
          refocusGridRef.current = true;
          commitEdit({
            row: editing.row,
            col: e.shiftKey
              ? Math.max(0, editing.col - 1)
              : Math.min(editing.col + 1, MAX_COLS - 1),
          });
          return;
      }
    },
    [editing, commitEdit, cancelEdit]
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLDivElement>) => {
      if (editing || readOnly) return;
      const { row, col } = sel.focus;
      // A pending cut takes precedence over the clipboard text: move the
      // snapshot to the focus cell and clear the source, in one transaction
      // (one undo step, one peer update). Formulas move verbatim — their
      // references stay pointing where they did, matching Excel's cut.
      if (cut) {
        e.preventDefault();
        const placed = offsetCells(cut.payload, row, col);
        const { r1, r2, c1, c2 } = cut.box;
        bulkUpdate((draft) => {
          for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) draft.delete(keyOf(r, c));
          for (const [key, value] of Object.entries(placed)) draft.set(key, value);
        });
        setSel({
          anchor: { row, col },
          focus: { row: row + (r2 - r1), col: col + (c2 - c1) },
          mode: "range",
        });
        setCut(null);
        return;
      }
      const text = e.clipboardData.getData("text/plain");
      if (!text) return;
      e.preventDefault();
      if (!text.includes("\n") && !text.includes("\t") && !text.includes(",")) {
        setCell(row, col, coerceScalar(text));
        return;
      }
      const delimiter = detectClipboardDelimiter(text);
      const parsed = csvToCells(text, { delimiter });
      const offset = offsetCells(parsed.cells, row, col);
      bulkUpdate((draft) => {
        for (const [key, value] of Object.entries(offset)) draft.set(key, value);
      });
    },
    [editing, readOnly, cut, sel.focus, setCell, bulkUpdate]
  );

  const handleCopy = useCallback(
    (e: ClipboardEvent<HTMLDivElement>) => {
      if (editing) return;
      setCut(null); // a fresh copy supersedes any pending cut
      const text = selectionToTsv();
      if (text === "") return;
      e.preventDefault();
      e.clipboardData.setData("text/plain", text);
    },
    [editing, selectionToTsv]
  );

  // Sort the whole sheet by a column (right-click a column header). Rows
  // are reordered as records, keeping every other column aligned; cell
  // values, per-cell styles, and per-row formatting all travel with the
  // row. Frozen header rows stay pinned (the sort starts below them).
  const handleSortColumn = useCallback(
    (col: number, direction: SortDirection) => {
      if (readOnly) return;
      setCut(null); // reordering rows would strand the cut marquee
      const result = sortSheetByColumn(cells, formatting.cellStyles, formatting.rows, {
        column: col,
        direction,
        startRow: formatting.frozen.rows,
      });
      if (!result.changed) return;
      // One transaction so peers see the reorder atomically and undo
      // rolls the whole sort back in a single step. The inner store
      // transacts flatten into this outer one (same pattern as import).
      docForData.transact(() => {
        bulkUpdate((draft) => {
          draft.clear();
          for (const [key, value] of Object.entries(result.cells)) draft.set(key, value);
        });
        formatting.replaceAll({
          columns: formatting.columns,
          rows: result.rows,
          cellStyles: result.cellStyles,
          frozen: formatting.frozen,
        });
      }, "spreadsheet-sort");
    },
    [readOnly, cells, formatting, bulkUpdate, docForData]
  );

  // Insert / delete whole rows or columns (right-click a header). The
  // pure ``transformSheet`` shifts every downstream line and remaps all
  // four index-keyed structures plus frozen + dimensions; we apply the
  // result in one transaction so peers see the structural change
  // atomically and undo rolls it back in a single step. ``replaceAll``
  // broadcasts the new dimensions through yMeta alongside the cells (the
  // import path's pattern) so a delete actually shrinks the canvas for
  // everyone instead of relying on the local-only auto-grow.
  const applyLineTransform = useCallback(
    (op: Pick<LineOp, "axis" | "mode" | "at" | "count">) => {
      if (readOnly) return;
      setCut(null); // shifting lines would strand the cut marquee
      const result = transformSheet(
        {
          cells,
          cellStyles: formatting.cellStyles,
          columns: formatting.columns,
          rows: formatting.rows,
          frozen: formatting.frozen,
          dimensions,
        },
        { ...op, maxRows: MAX_ROWS, maxCols: MAX_COLS }
      );
      if (!result) {
        // The op was blocked by a guard (deleting the last remaining
        // line, or inserting into a grid already at MAX). Surface why so
        // the silent no-op is discoverable.
        const blockedKey =
          op.mode === "delete"
            ? op.axis === "row"
              ? "spreadsheet.deleteLastRowBlocked"
              : "spreadsheet.deleteLastColumnBlocked"
            : op.axis === "row"
              ? "spreadsheet.maxRowsReached"
              : "spreadsheet.maxColumnsReached";
        toast.info(t(`documents:${blockedKey}`));
        return;
      }
      docForData.transact(() => {
        replaceAll(result.cells, result.dimensions);
        formatting.replaceAll({
          columns: result.columns,
          rows: result.rows,
          cellStyles: result.cellStyles,
          frozen: result.frozen,
        });
      }, "spreadsheet-structure");

      // Remap the selection along the shifted axis so it tracks the same
      // content — otherwise an insert-above leaves the stale band straddling
      // the freshly inserted blank lines, and a later right-click would
      // delete more than intended. ``delta`` is signed and respects capping:
      // > 0 inserted, < 0 deleted.
      const axisIsRow = op.axis === "row";
      const at = Math.max(0, Math.trunc(op.at));
      const delta =
        (axisIsRow ? result.dimensions.rows : result.dimensions.cols) -
        (axisIsRow ? dimensions.rows : dimensions.cols);
      const newDim = axisIsRow ? result.dimensions.rows : result.dimensions.cols;
      const remapIdx = (i: number): number => {
        if (delta >= 0) return i >= at ? i + delta : i; // insert
        const removed = -delta;
        if (i < at) return i;
        if (i >= at + removed) return i - removed;
        return Math.min(at, newDim - 1); // line was inside the deleted band
      };
      setSel((p) => ({
        mode: p.mode,
        anchor: axisIsRow
          ? { row: remapIdx(p.anchor.row), col: p.anchor.col }
          : { row: p.anchor.row, col: remapIdx(p.anchor.col) },
        focus: axisIsRow
          ? { row: remapIdx(p.focus.row), col: p.focus.col }
          : { row: p.focus.row, col: remapIdx(p.focus.col) },
      }));

      if (result.capped) {
        // Fewer lines than requested were applied — a guard kept the last
        // line (delete) or the grid cap left room for only some (insert).
        // Hint so the leftover/missing line isn't a silent mystery.
        const cappedKey =
          op.mode === "delete"
            ? op.axis === "row"
              ? "spreadsheet.deleteLastRowKept"
              : "spreadsheet.deleteLastColumnKept"
            : op.axis === "row"
              ? "spreadsheet.insertRowsCapped"
              : "spreadsheet.insertColumnsCapped";
        toast.info(t(`documents:${cappedKey}`));
      }
    },
    [readOnly, cells, formatting, dimensions, replaceAll, docForData, t]
  );

  // Insert ``count`` lines before / after the band on ``axis``, then
  // delete the whole band. "before" = left/above (at the band start);
  // "after" = right/below (just past the band end).
  const insertLines = useCallback(
    (axis: LineAxis, band: { start: number; count: number }, count: number, after: boolean) => {
      applyLineTransform({
        axis,
        mode: "insert",
        at: after ? band.start + band.count : band.start,
        count,
      });
    },
    [applyLineTransform]
  );
  const deleteLines = useCallback(
    (axis: LineAxis, band: { start: number; count: number }) => {
      applyLineTransform({ axis, mode: "delete", at: band.start, count: band.count });
    },
    [applyLineTransform]
  );

  // --- column / row resize ----------------------------------------------
  // Listeners are attached synchronously inside startResize (the pointerdown
  // handler) so there is never a gap between "drag started" and "pointerup
  // is handled".  The previous useEffect approach had an inherent race: React
  // defers effects until after paint, so a quick release (common on Mac
  // trackpads) could fire pointerup before the effect had a chance to run.
  //
  // An AbortController owns listener lifetime so:
  //   - commit / cancel both tear down with a single ``.abort()`` call
  //   - the unmount effect (below) aborts an in-flight drag, preventing a
  //     stale ``formattingRef.current.updateColumn`` write into a Yjs doc
  //     whose view has already been unmounted.
  const startResize = useCallback(
    (kind: "col" | "row", index: number, e: ReactPointerEvent) => {
      if (readOnly) return;
      e.preventDefault();
      e.stopPropagation();
      const size = kind === "col" ? colWidth(index) : rowHeight(index);
      resizeStartRef.current = {
        pos: kind === "col" ? e.clientX : e.clientY,
        size,
      };
      const next = { kind, index, size };
      dragRef.current = next;
      setDrag(next);

      // Abort any previous drag's listeners (defensive — shouldn't happen,
      // but a missed pointerup would otherwise leak them indefinitely).
      resizeAbortRef.current?.abort();
      const controller = new AbortController();
      resizeAbortRef.current = controller;
      const { signal } = controller;

      const onMove = (ev: PointerEvent) => {
        const cur = dragRef.current;
        if (!cur) return;
        const delta =
          cur.kind === "col"
            ? ev.clientX - resizeStartRef.current.pos
            : ev.clientY - resizeStartRef.current.pos;
        const lo = cur.kind === "col" ? MIN_COL_WIDTH : MIN_ROW_HEIGHT;
        const hi = cur.kind === "col" ? MAX_COL_WIDTH : MAX_ROW_HEIGHT;
        // Round to integer: pointer coords are fractional on Retina/Mac, and
        // sanitizeColumnFmt/RowFmt drop non-integer sizes (clampInt requires
        // Number.isInteger), which previously caused the commit to silently
        // delete the entry and revert to the default width/height.
        const newSize = Math.round(Math.max(lo, Math.min(resizeStartRef.current.size + delta, hi)));
        const updated = { ...cur, size: newSize };
        dragRef.current = updated;
        setDrag(updated);
      };

      const teardown = () => {
        controller.abort();
        if (resizeAbortRef.current === controller) resizeAbortRef.current = null;
        dragRef.current = null;
        setDrag(null);
      };

      const commit = () => {
        const cur = dragRef.current;
        if (cur) {
          const fmt = formattingRef.current;
          if (cur.kind === "col") fmt.updateColumn(cur.index, { width: cur.size });
          else fmt.updateRow(cur.index, { height: cur.size });
        }
        teardown();
      };

      // pointercancel fires on Mac when the OS reclassifies a trackpad
      // gesture as a scroll — the user wasn't trying to resize, so discard
      // the in-flight drag instead of writing whatever intermediate size
      // it happened to reach.
      const cancel = () => {
        teardown();
      };

      window.addEventListener("pointermove", onMove, { signal });
      window.addEventListener("pointerup", commit, { signal });
      window.addEventListener("pointercancel", cancel, { signal });
    },
    [readOnly, colWidth, rowHeight]
  );

  // Abort any in-flight resize drag when the editor unmounts so the window
  // listeners can't fire against a stale formattingRef afterwards.
  useEffect(() => {
    return () => {
      resizeAbortRef.current?.abort();
      resizeAbortRef.current = null;
    };
  }, []);
  const resetSize = useCallback(
    (kind: "col" | "row", index: number) => {
      if (readOnly) return;
      if (kind === "col") formatting.updateColumn(index, { width: undefined });
      else formatting.updateRow(index, { height: undefined });
    },
    [readOnly, formatting]
  );

  const totalGridWidth = colVirtualizer.getTotalSize();
  const totalGridHeight = rowVirtualizer.getTotalSize();

  const { rows: frozenRows, cols: frozenCols } = formatting.frozen;
  const prefixRow = useMemo(() => {
    const out = [0];
    for (let r = 0; r < frozenRows; r++) out.push(out[r] + rowHeight(r));
    return out;
  }, [frozenRows, rowHeight]);
  const prefixCol = useMemo(() => {
    const out = [0];
    for (let c = 0; c < frozenCols; c++) out.push(out[c] + colWidth(c));
    return out;
  }, [frozenCols, colWidth]);
  const frozenBandHeight = prefixRow[frozenRows] ?? 0;
  const frozenBandWidth = prefixCol[frozenCols] ?? 0;

  const renderCell = useCallback(
    (r: number, c: number, left: number, top: number) => {
      const isActive = sel.focus.row === r && sel.focus.col === c;
      const isEditing = editing?.row === r && editing?.col === c;
      const value = cells.get(keyOf(r, c));
      const numberFormat = resolveCellFormat(r, c, formatting);
      // Formula cells show their computed result (or an error token); the
      // raw "=..." text is what ``beginEdit`` puts back in the input. The
      // computed result also drives number formatting and the red-negative
      // rule, exactly as a literal value would.
      const evaluated = isFormula(value) ? evaluator.evaluate(r, c) : null;
      const error = evaluated?.error ?? null;
      const resolved = evaluated ? evaluated.value : (value ?? null);
      const display = isEditing
        ? ""
        : error
          ? error
          : resolved == null
            ? ""
            : formatCellValue(resolved, numberFormat);
      const isBoolean = typeof value === "boolean" && !numberFormat;
      const peer = peerSelectionsByCell.get(keyOf(r, c));
      const inCut = cut
        ? r >= cut.box.r1 && r <= cut.box.r2 && c >= cut.box.c1 && c <= cut.box.c2
        : false;
      const cellCss = styleToCss(resolveCellStyle(r, c, formatting));
      // A formula error, or a red/redParens negative number, wins over any
      // explicit text color (Excel's numFmt color section overrides font).
      if (error || negativeRendersRed(resolved, numberFormat)) cellCss.color = "#dc2626";
      // The fill handle sits on the bottom-right corner of a cell-range
      // selection; the preview tint covers the live drag extent.
      const isFillCorner =
        !readOnly && !isEditing && sel.mode === "range" && r === selBox.r2 && c === selBox.c2;
      const inFillPreview = fillPreview
        ? r >= fillPreview.r1 && r <= fillPreview.r2 && c >= fillPreview.c1 && c <= fillPreview.c2
        : false;
      return (
        <CellView
          key={keyOf(r, c)}
          style={{ left, top, width: colWidth(c), height: rowHeight(r) }}
          cellCss={cellCss}
          isActive={isActive}
          inSelection={isInSel(r, c)}
          inCut={inCut}
          inFillPreview={inFillPreview}
          showFillHandle={isFillCorner}
          isEditing={Boolean(isEditing)}
          display={display}
          title={error ?? undefined}
          booleanValue={isBoolean ? (value as boolean) : null}
          readOnly={readOnly}
          draft={isEditing ? editing!.draft : ""}
          inputRef={isEditing ? editingInputRef : null}
          peerColor={peer?.selection.color ?? null}
          peerName={peer?.user.name ?? null}
          refHighlight={refHighlightAt(r, c)}
          refTokens={isEditing ? editingRefs : EMPTY_REF_TOKENS}
          onMouseDown={(e) => {
            if (isEditing) return;
            if (e.button !== 0) return;
            // Point mode: while editing a formula, clicking another cell
            // splices its reference into the draft instead of moving the
            // selection. preventDefault keeps the input focused (no blur →
            // no commit). A null return means "not a reference spot" — fall
            // through to a normal, committing click.
            if (editing && isFormula(editing.draft)) {
              // Shift-click extends the last inserted reference into a range;
              // a plain click inserts/moves a single reference.
              const extend = e.shiftKey && pointRefRef.current !== null;
              if (insertReference(r, c, extend)) {
                e.preventDefault();
                pointDraggingRef.current = true;
                return;
              }
            }
            containerRef.current?.focus();
            selectingRef.current = "range";
            selectCell(r, c, e.shiftKey);
          }}
          onMouseEnter={(e) => {
            // A point-mode drag (button still held) extends the reference into
            // a range. Gate on the live button state (``e.buttons``) rather
            // than only the flag, so a missed mouseup (release off-window, HMR)
            // can't leave the drag stuck following the cursor.
            if (pointDraggingRef.current) {
              if (e.buttons === 0) {
                pointDraggingRef.current = false;
              } else {
                insertReference(r, c, true);
                return;
              }
            }
            // A fill drag in progress takes over hover: extend its preview
            // instead of moving the selection focus.
            if (fillSourceRef.current) {
              extendFill(r, c);
              return;
            }
            if (selectingRef.current !== "range") return;
            setSel((p) => ({
              anchor: p.anchor,
              focus: { row: r, col: c },
              mode: "range",
            }));
          }}
          onFillHandleMouseDown={startFill}
          onFillHandleDoubleClick={autofillDown}
          onDoubleClick={() => beginEdit(r, c)}
          onToggleBoolean={() => {
            if (readOnly || !isBoolean) return;
            selectCell(r, c);
            setCell(r, c, !(value as boolean));
          }}
          onDraftChange={(draft) => {
            // Typing invalidates the recorded reference span, so a later
            // shift-click starts a fresh reference rather than re-splicing.
            pointRefRef.current = null;
            setEditing({ row: r, col: c, draft });
          }}
          onEditingKeyDown={handleEditingKeyDown}
          onEditingBlur={handleEditorBlur}
          onEditingFocus={() => {
            activeEditorRef.current = editingInputRef.current;
          }}
        />
      );
    },
    [
      cells,
      evaluator,
      formatting,
      sel.focus,
      sel.mode,
      selBox,
      isInSel,
      cut,
      fillPreview,
      editing,
      editingRefs,
      refHighlightAt,
      insertReference,
      readOnly,
      peerSelectionsByCell,
      colWidth,
      rowHeight,
      selectCell,
      beginEdit,
      setCell,
      handleEditingKeyDown,
      handleEditorBlur,
      startFill,
      autofillDown,
      extendFill,
    ]
  );

  // The name box label: the active cell ref, or the selection range / band.
  const formulaBarLabel = useMemo(() => {
    const { r1, r2, c1, c2 } = selBox;
    if (sel.mode === "columns") {
      return c1 === c2 ? colIndexToLetter(c1) : `${colIndexToLetter(c1)}:${colIndexToLetter(c2)}`;
    }
    if (sel.mode === "rows") return r1 === r2 ? `${r1 + 1}` : `${r1 + 1}:${r2 + 1}`;
    const ref = (r: number, c: number) => `${colIndexToLetter(c)}${r + 1}`;
    return r1 === r2 && c1 === c2 ? ref(r1, c1) : `${ref(r1, c1)}:${ref(r2, c2)}`;
  }, [sel.mode, selBox]);

  // The formula bar mirrors the live edit draft, else the focus cell's raw
  // value (its formula/value as stored, not the computed result).
  const formulaBarValue = useMemo(() => {
    if (editing) return editing.draft;
    const raw = cells.get(keyOf(sel.focus.row, sel.focus.col));
    return raw == null ? "" : String(raw);
  }, [editing, cells, sel.focus.row, sel.focus.col]);

  // Focusing the bar begins an edit of the focus cell (unless one is already
  // live); the flag keeps focus in the bar instead of the cell input.
  const handleFormulaBarFocus = useCallback(() => {
    activeEditorRef.current = formulaBarInputRef.current;
    if (readOnly || editing) return;
    focusBarOnEditRef.current = true;
    beginEdit(sel.focus.row, sel.focus.col);
  }, [readOnly, editing, beginEdit, sel.focus.row, sel.focus.col]);

  const handleFormulaBarChange = useCallback(
    (draft: string) => {
      pointRefRef.current = null;
      setEditing((p) => (p ? { ...p, draft } : { row: sel.focus.row, col: sel.focus.col, draft }));
    },
    [sel.focus.row, sel.focus.col]
  );

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border border-border bg-background",
        className
      )}
    >
      <div className="flex shrink-0 items-center gap-2 overflow-x-auto border-border border-b bg-muted/20 px-3 py-2">
        <SpreadsheetToolbar
          selection={
            {
              mode: sel.mode,
              r1: selBox.r1,
              r2: selBox.r2,
              c1: selBox.c1,
              c2: selBox.c2,
              focusRow: sel.focus.row,
              focusCol: sel.focus.col,
            } satisfies ToolbarSelection
          }
          formatting={formatting}
          readOnly={readOnly}
          onInsertFunction={insertFunction}
          onUndo={history.undo}
          onRedo={history.redo}
          canUndo={history.canUndo}
          canRedo={history.canRedo}
        />
      </div>

      <SpreadsheetFormulaBar
        selectionLabel={formulaBarLabel}
        onNavigate={navigateToRef}
        value={formulaBarValue}
        tokens={editingRefs}
        inputRef={formulaBarInputRef}
        onChange={handleFormulaBarChange}
        onFocus={handleFormulaBarFocus}
        onKeyDown={handleEditingKeyDown}
        onBlur={handleEditorBlur}
        readOnly={readOnly}
      />

      {/* biome-ignore lint/a11y/useSemanticElements: virtualized absolute layout doesn't fit a <table>; ARIA grid roles convey semantics */}
      <div
        ref={containerRef}
        role="grid"
        tabIndex={0}
        aria-label={documentTitle}
        aria-rowcount={dimensions.rows}
        aria-colcount={dimensions.cols}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onCopy={handleCopy}
        className="relative min-h-0 flex-1 select-none overflow-auto focus:outline-none focus-visible:outline-2 focus-visible:outline-primary"
      >
        <div
          style={{
            width: ROW_HEADER_WIDTH + totalGridWidth,
            height: COL_HEADER_HEIGHT + totalGridHeight,
            position: "relative",
          }}
        >
          {/* Column-header strip — sticky top keeps letters glued while
              scrolling vertically. */}
          <div
            className="sticky top-0 z-20 bg-muted"
            style={{
              left: 0,
              height: COL_HEADER_HEIGHT,
              width: ROW_HEADER_WIDTH + totalGridWidth,
            }}
          >
            <div
              className="sticky top-0 left-0 z-30 border-border border-r border-b bg-muted"
              style={{ width: ROW_HEADER_WIDTH, height: COL_HEADER_HEIGHT }}
            />
            {virtualCols.map((col) => {
              const header = (
                <button
                  type="button"
                  onMouseDown={(e) => {
                    if (e.button !== 0) return;
                    containerRef.current?.focus();
                    selectingRef.current = "columns";
                    selectColumn(col.index, e.shiftKey);
                  }}
                  onContextMenu={() => {
                    // Highlight the column the menu will act on (right-click
                    // doesn't go through the left-button onMouseDown path).
                    // Keep an existing multi-column selection if the click
                    // lands inside it so the menu acts on the whole band.
                    containerRef.current?.focus();
                    if (!(sel.mode === "columns" && colHeaderActive(col.index)))
                      selectColumn(col.index);
                  }}
                  onMouseEnter={() => {
                    if (selectingRef.current !== "columns") return;
                    setSel((p) => ({
                      anchor: p.anchor,
                      focus: { row: 0, col: col.index },
                      mode: "columns",
                    }));
                  }}
                  className={cn(
                    "absolute flex cursor-pointer items-center justify-center border-border border-r border-b font-mono text-xs",
                    colHeaderActive(col.index)
                      ? "bg-primary/20 text-foreground"
                      : "bg-muted text-muted-foreground"
                  )}
                  style={{
                    left: ROW_HEADER_WIDTH + col.start,
                    top: 0,
                    width: col.size,
                    height: COL_HEADER_HEIGHT,
                  }}
                >
                  {colIndexToLetter(col.index)}
                  {!readOnly && (
                    <div
                      onMouseDown={(e) => e.stopPropagation()}
                      onPointerDown={(e) => startResize("col", col.index, e)}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        resetSize("col", col.index);
                      }}
                      className="absolute top-0 right-0 z-10 h-full cursor-col-resize hover:bg-primary/40"
                      style={{ width: RESIZE_HANDLE }}
                      aria-hidden
                    />
                  )}
                </button>
              );
              if (readOnly) return <Fragment key={`colh-${col.index}`}>{header}</Fragment>;
              const band = lineBand("col", col.index);
              return (
                <HeaderContextMenu
                  key={`colh-${col.index}`}
                  axis="col"
                  band={band}
                  onInsert={(count, after) => insertLines("col", band, count, after)}
                  onDelete={() => deleteLines("col", band)}
                  onSort={(direction) => handleSortColumn(col.index, direction)}
                >
                  {header}
                </HeaderContextMenu>
              );
            })}
          </div>

          {/* Frozen panes use CSS ``position: sticky`` (compositor-driven)
              instead of per-frame JS repositioning, so they no longer lag a
              render behind the scroll. Each band is a zero-size sticky
              positioning context placed in flow right after the column header
              (natural top = COL_HEADER_HEIGHT, so it pins there); an opaque
              backing rect masks the body cells scrolling underneath. Only the
              axis that should stay frozen gets a sticky inset — the other axis
              has no inset and scrolls naturally with the body. */}

          {/* Frozen rows band — pinned vertically (sticky top), scrolls
              horizontally with the body. */}
          {frozenRows > 0 && (
            <div
              className="sticky"
              style={{ top: COL_HEADER_HEIGHT, width: 0, height: 0, zIndex: 6 }}
            >
              <div
                className="absolute bg-background"
                style={{
                  left: ROW_HEADER_WIDTH,
                  top: 0,
                  width: totalGridWidth,
                  height: frozenBandHeight,
                }}
              />
              {virtualCols.map((col) =>
                col.index < frozenCols
                  ? null
                  : Array.from({ length: frozenRows }, (_, r) =>
                      renderCell(r, col.index, ROW_HEADER_WIDTH + col.start, prefixRow[r])
                    )
              )}
            </div>
          )}

          {/* Frozen cols band — pinned horizontally (sticky left), scrolls
              vertically with the body. */}
          {frozenCols > 0 && (
            <div
              className="sticky"
              style={{ left: ROW_HEADER_WIDTH, width: 0, height: 0, zIndex: 5 }}
            >
              <div
                className="absolute bg-background"
                style={{ left: 0, top: 0, width: frozenBandWidth, height: totalGridHeight }}
              />
              {virtualRows.map((row) =>
                row.index < frozenRows
                  ? null
                  : Array.from({ length: frozenCols }, (_, c) =>
                      renderCell(row.index, c, prefixCol[c], row.start)
                    )
              )}
            </div>
          )}

          {/* Frozen corner — pinned on both axes. */}
          {frozenRows > 0 && frozenCols > 0 && (
            <div
              className="sticky"
              style={{
                top: COL_HEADER_HEIGHT,
                left: ROW_HEADER_WIDTH,
                width: 0,
                height: 0,
                zIndex: 7,
              }}
            >
              <div
                className="absolute bg-background"
                style={{ left: 0, top: 0, width: frozenBandWidth, height: frozenBandHeight }}
              />
              {Array.from({ length: frozenRows }, (_, r) =>
                Array.from({ length: frozenCols }, (_, c) =>
                  renderCell(r, c, prefixCol[c], prefixRow[r])
                )
              )}
            </div>
          )}

          {/* Row-header strip — sticky left keeps numbers glued while
              scrolling horizontally. */}
          <div
            className="sticky left-0 z-10 bg-muted"
            style={{ width: ROW_HEADER_WIDTH, height: totalGridHeight }}
          >
            {virtualRows.map((row) => {
              const header = (
                <button
                  type="button"
                  onMouseDown={(e) => {
                    if (e.button !== 0) return;
                    containerRef.current?.focus();
                    selectingRef.current = "rows";
                    selectRow(row.index, e.shiftKey);
                  }}
                  onContextMenu={() => {
                    // Highlight the row the menu will act on; keep an
                    // existing multi-row selection if the click lands inside
                    // it so the menu acts on the whole band.
                    containerRef.current?.focus();
                    if (!(sel.mode === "rows" && rowHeaderActive(row.index))) selectRow(row.index);
                  }}
                  onMouseEnter={() => {
                    if (selectingRef.current !== "rows") return;
                    setSel((p) => ({
                      anchor: p.anchor,
                      focus: { row: row.index, col: 0 },
                      mode: "rows",
                    }));
                  }}
                  className={cn(
                    "absolute flex cursor-pointer items-center justify-center border-border border-r border-b font-mono text-xs",
                    rowHeaderActive(row.index)
                      ? "bg-primary/20 text-foreground"
                      : "bg-muted text-muted-foreground"
                  )}
                  style={{
                    left: 0,
                    top: row.start,
                    width: ROW_HEADER_WIDTH,
                    height: row.size,
                  }}
                >
                  {row.index + 1}
                  {!readOnly && (
                    <div
                      onMouseDown={(e) => e.stopPropagation()}
                      onPointerDown={(e) => startResize("row", row.index, e)}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        resetSize("row", row.index);
                      }}
                      className="absolute bottom-0 left-0 z-10 w-full cursor-row-resize hover:bg-primary/40"
                      style={{ height: RESIZE_HANDLE }}
                      aria-hidden
                    />
                  )}
                </button>
              );
              if (readOnly) return <Fragment key={`rowh-${row.index}`}>{header}</Fragment>;
              const band = lineBand("row", row.index);
              return (
                <HeaderContextMenu
                  key={`rowh-${row.index}`}
                  axis="row"
                  band={band}
                  onInsert={(count, after) => insertLines("row", band, count, after)}
                  onDelete={() => deleteLines("row", band)}
                >
                  {header}
                </HeaderContextMenu>
              );
            })}
          </div>

          {/* Body cells (excludes anything covered by a frozen band). */}
          {virtualRows.map((row) =>
            virtualCols.map((col) => {
              if (row.index < frozenRows || col.index < frozenCols) return null;
              return renderCell(
                row.index,
                col.index,
                ROW_HEADER_WIDTH + col.start,
                COL_HEADER_HEIGHT + row.start
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

/** Largest N the "insert multiple" stepper accepts; the transform also
 *  clamps to the remaining grid capacity, this just keeps the input sane. */
const MAX_INSERT_N = 1_000;
/** Stepper default — reset on every menu open so a value typed for one
 *  header never bleeds into another (the menus are keyed by index, so React
 *  reuses an instance across different rows/cols after an insert/delete). */
const DEFAULT_INSERT_N = 2;

interface HeaderContextMenuProps {
  axis: LineAxis;
  /** The contiguous band the menu acts on: the active multi-selection
   *  when it covers this header, otherwise just the clicked line. */
  band: { start: number; count: number };
  onInsert: (count: number, after: boolean) => void;
  onDelete: () => void;
  /** Columns only — sort the whole sheet by this column. */
  onSort?: (direction: SortDirection) => void;
  /** The header button that triggers the menu. */
  children: React.ReactNode;
}

/** Right-click menu shared by the row and column headers: insert one
 *  line either side, insert N via a stepper submenu, or delete the
 *  selected band. Column headers additionally get the sort actions. */
const HeaderContextMenu = ({
  axis,
  band,
  onInsert,
  onDelete,
  onSort,
  children,
}: HeaderContextMenuProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const [n, setN] = useState(DEFAULT_INSERT_N);
  const isRow = axis === "row";
  const before = isRow ? "insertRowAbove" : "insertColumnLeft";
  const after = isRow ? "insertRowBelow" : "insertColumnRight";
  const beforeN = isRow ? "insertRowsAboveN" : "insertColumnsLeftN";
  const afterN = isRow ? "insertRowsBelowN" : "insertColumnsRightN";

  return (
    <ContextMenu onOpenChange={(open) => open && setN(DEFAULT_INSERT_N)}>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={() => onInsert(1, false)}>
          {t(`documents:spreadsheet.${before}`)}
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => onInsert(1, true)}>
          {t(`documents:spreadsheet.${after}`)}
        </ContextMenuItem>
        <ContextMenuSub>
          <ContextMenuSubTrigger>{t("documents:spreadsheet.insertMultiple")}</ContextMenuSubTrigger>
          <ContextMenuSubContent>
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span className="text-muted-foreground text-xs">
                {t("documents:spreadsheet.insertCount")}
              </span>
              <input
                type="number"
                min={1}
                max={MAX_INSERT_N}
                value={n}
                // biome-ignore lint/a11y/noAutofocus: focuses the stepper when the submenu opens so the user can type N immediately
                autoFocus
                // Keep keystrokes in the input — otherwise the menu's
                // typeahead steals them and jumps focus to an item.
                onKeyDown={(e) => e.stopPropagation()}
                onFocus={(e) => e.currentTarget.select()}
                onChange={(e) => {
                  const next = Number.parseInt(e.target.value, 10);
                  setN(Number.isFinite(next) ? Math.max(1, Math.min(next, MAX_INSERT_N)) : 1);
                }}
                className="w-16 rounded border border-border bg-background px-1.5 py-0.5 text-sm outline-none focus:border-primary"
              />
            </div>
            <ContextMenuItem onSelect={() => onInsert(n, false)}>
              {t(`documents:spreadsheet.${beforeN}`, { count: n })}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => onInsert(n, true)}>
              {t(`documents:spreadsheet.${afterN}`, { count: n })}
            </ContextMenuItem>
          </ContextMenuSubContent>
        </ContextMenuSub>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={onDelete} className="text-destructive focus:text-destructive">
          {t(isRow ? "documents:spreadsheet.deleteRows" : "documents:spreadsheet.deleteColumns", {
            count: band.count,
          })}
        </ContextMenuItem>
        {onSort && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onSelect={() => onSort("asc")}>
              {t("documents:spreadsheet.sortAscending")}
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => onSort("desc")}>
              {t("documents:spreadsheet.sortDescending")}
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
};

interface CellViewProps {
  style: CSSProperties;
  /** Resolved style/format CSS (background, color, weight, align). */
  cellCss: CSSProperties;
  /** The focus cell — strong ring, the keyboard/edit target. */
  isActive: boolean;
  /** Inside the current selection (but not the focus cell). */
  inSelection: boolean;
  /** Inside the pending-cut source — draws a dashed "move" marquee. */
  inCut: boolean;
  /** Inside the live fill-handle drag extent — draws a preview tint. */
  inFillPreview: boolean;
  /** This is the selection's bottom-right corner — renders the fill nub. */
  showFillHandle: boolean;
  isEditing: boolean;
  display: string;
  /** Tooltip text — used to surface a formula error token (e.g. #DIV/0!). */
  title?: string;
  booleanValue: boolean | null;
  readOnly: boolean;
  draft: string;
  inputRef: React.RefObject<HTMLInputElement | null> | null;
  /** Colors this cell as a referenced cell of the formula being edited. */
  refHighlight: RefHighlight | null;
  /** References in the editing draft — colors the in-cell formula text. */
  refTokens: FormulaRefToken[];
  peerColor: string | null;
  peerName: string | null;
  onMouseDown: (e: React.MouseEvent) => void;
  onMouseEnter: (e: React.MouseEvent) => void;
  onDoubleClick: () => void;
  onToggleBoolean: () => void;
  onDraftChange: (draft: string) => void;
  onEditingKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  onEditingBlur: (e: React.FocusEvent<HTMLInputElement>) => void;
  onEditingFocus: () => void;
  onFillHandleMouseDown: () => void;
  onFillHandleDoubleClick: () => void;
}

const CellView = ({
  style,
  cellCss,
  isActive,
  inSelection,
  inCut,
  inFillPreview,
  showFillHandle,
  isEditing,
  display,
  title,
  booleanValue,
  readOnly,
  draft,
  inputRef,
  refHighlight,
  refTokens,
  peerColor,
  peerName,
  onMouseDown,
  onMouseEnter,
  onDoubleClick,
  onToggleBoolean,
  onDraftChange,
  onEditingKeyDown,
  onEditingBlur,
  onEditingFocus,
  onFillHandleMouseDown,
  onFillHandleDoubleClick,
}: CellViewProps) => {
  const baseClass = useMemo(
    () =>
      cn(
        "absolute box-border border-border border-r border-b text-sm",
        (isActive || isEditing) && "z-[1] ring-2 ring-primary ring-inset"
      ),
    [isActive, isEditing]
  );
  // Fill must sit *under* the value/ring; positioning + fill on the
  // container, text styling inherited by the value span.
  const containerStyle = useMemo<CSSProperties>(
    () => ({ position: "absolute", ...style, ...cellCss }),
    [style, cellCss]
  );

  const peerOverlay =
    peerColor && peerName ? (
      <div
        className="pointer-events-none absolute inset-0 z-[2]"
        style={{ boxShadow: `inset 0 0 0 2px ${peerColor}` }}
      >
        <div
          className="absolute -top-4 right-0 max-w-full truncate rounded-t px-1.5 py-0.5 font-medium text-[10px] text-slate-900 shadow-sm"
          style={{ backgroundColor: peerColor }}
        >
          {peerName}
        </div>
      </div>
    ) : null;

  // Translucent tint for non-focus cells in the selection so the user
  // fill underneath still reads through.
  const selectionOverlay =
    inSelection && !isActive ? (
      <div className="pointer-events-none absolute inset-0 bg-primary/15" />
    ) : null;

  // Dashed "move" marquee on a cell awaiting a cut-paste.
  const cutOverlay = inCut ? (
    <div className="pointer-events-none absolute inset-0 z-[1] border-2 border-primary border-dashed" />
  ) : null;

  // Tint over the new region a fill drag will write (the source already
  // reads through the selection tint, so only paint cells outside it).
  const fillPreviewOverlay =
    inFillPreview && !inSelection && !isActive ? (
      <div className="pointer-events-none absolute inset-0 bg-primary/10" />
    ) : null;

  // Colored outline marking this cell as a reference of the formula being
  // edited. Borders only on the box-boundary edges so a range reads as one
  // rectangle rather than a grid of boxes.
  const refOverlay = refHighlight ? (
    <div
      className="pointer-events-none absolute inset-0 z-[2]"
      style={{
        borderColor: refHighlight.color,
        borderStyle: "solid",
        borderTopWidth: refHighlight.top ? 2 : 0,
        borderBottomWidth: refHighlight.bottom ? 2 : 0,
        borderLeftWidth: refHighlight.left ? 2 : 0,
        borderRightWidth: refHighlight.right ? 2 : 0,
      }}
    />
  ) : null;

  // The draggable fill handle on the selection's bottom-right corner. Its
  // own mousedown starts the fill (stopping selection); double-click
  // auto-fills down. Centered on the corner, above the ring/overlays.
  const fillHandle = showFillHandle ? (
    // biome-ignore lint/a11y/noStaticElementInteractions: pointer-only affordance; grid keyboard model owns navigation
    <div
      className="absolute right-0 bottom-0 z-[3] h-[7px] w-[7px] translate-x-1/2 translate-y-1/2 cursor-crosshair rounded-[1px] border border-background bg-primary"
      onMouseDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
        onFillHandleMouseDown();
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        onFillHandleDoubleClick();
      }}
    />
  ) : null;

  if (isEditing) {
    return (
      <div className={baseClass} style={containerStyle}>
        <FormulaCellInput
          inputRef={inputRef}
          value={draft}
          tokens={refTokens}
          onChange={onDraftChange}
          onKeyDown={onEditingKeyDown}
          onBlur={onEditingBlur}
          onFocus={onEditingFocus}
        />
        {peerOverlay}
      </div>
    );
  }

  if (booleanValue !== null) {
    return (
      // biome-ignore lint/a11y/noStaticElementInteractions: cell is part of a role="grid" widget; keyboard/selection is owned by the container
      <div
        className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
        style={containerStyle}
        onMouseDown={onMouseDown}
        onMouseEnter={onMouseEnter}
        onDoubleClick={onDoubleClick}
      >
        <Checkbox
          checked={booleanValue}
          disabled={readOnly}
          onClick={(e) => {
            e.stopPropagation();
            onToggleBoolean();
          }}
          aria-label={booleanValue ? "true" : "false"}
        />
        {selectionOverlay}
        {fillPreviewOverlay}
        {refOverlay}
        {cutOverlay}
        {peerOverlay}
        {fillHandle}
      </div>
    );
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: cell is part of a role="grid" widget; keyboard/selection is owned by the container
    <div
      className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
      style={containerStyle}
      title={title}
      onMouseDown={onMouseDown}
      onMouseEnter={onMouseEnter}
      onDoubleClick={onDoubleClick}
    >
      <span className="w-full truncate">{display}</span>
      {selectionOverlay}
      {fillPreviewOverlay}
      {refOverlay}
      {cutOverlay}
      {peerOverlay}
      {fillHandle}
    </div>
  );
};
