import type { ProviderAwareness } from "@lexical/yjs";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  type ChangeEvent,
  type ClipboardEvent,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import * as Y from "yjs";

import {
  SpreadsheetToolbar,
  type ToolbarSelection,
} from "@/components/documents/spreadsheet/SpreadsheetToolbar";
import { useSpreadsheetAwareness } from "@/components/documents/spreadsheet/useSpreadsheetAwareness";
import { useSpreadsheetCells } from "@/components/documents/spreadsheet/useSpreadsheetCells";
import { useSpreadsheetFormatting } from "@/components/documents/spreadsheet/useSpreadsheetFormatting";
import { useSpreadsheetHistory } from "@/components/documents/spreadsheet/useSpreadsheetHistory";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { matchHistoryShortcut } from "@/hooks/useYjsHistory";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { type CellValue, colIndexToLetter, keyOf, parseKey } from "@/lib/spreadsheet/coords";
import {
  cellsToCsv,
  coerceScalar,
  csvToCells,
  detectClipboardDelimiter,
  offsetCells,
} from "@/lib/spreadsheet/csv";
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
import { cellsToXlsx, xlsxToContent } from "@/lib/spreadsheet/xlsx";
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

const slugify = (s: string): string =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "spreadsheet";

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
  const [drag, setDrag] = useState<DragState | null>(null);
  // Which header/cell drag is in progress (null = not dragging).
  const selectingRef = useRef<null | "range" | "columns" | "rows">(null);
  const [pendingImport, setPendingImport] = useState<{
    cells: Record<string, CellValue>;
    rows: number;
    cols: number;
    formatting?: SpreadsheetFormatting;
  } | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const editingInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
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

  // Clear the selectingRef on any pointer release so a drag that ends
  // off-grid still stops extending the selection.
  useEffect(() => {
    const onUp = () => {
      selectingRef.current = null;
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
      if (next) selectCell(next.row, next.col);
    },
    [editing, setCell, selectCell]
  );

  const cancelEdit = useCallback(() => {
    setEditing(null);
  }, []);

  const editingCellKey = editing ? `${editing.row}:${editing.col}` : null;
  useEffect(() => {
    if (editingCellKey && editingInputRef.current) {
      editingInputRef.current.focus();
    }
  }, [editingCellKey]);

  // Delete every cell value covered by the selection. For a range that's
  // the rectangle; for whole-column/row selections, only the cells that
  // actually hold data (the map is sparse) so a clear is bounded.
  const clearSelection = useCallback(() => {
    if (readOnly) return;
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
      const { row, col } = sel.focus;
      switch (e.key) {
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
          commitEdit({ row: editing.row + 1, col: editing.col });
          return;
        case "Escape":
          e.preventDefault();
          cancelEdit();
          return;
        case "Tab":
          e.preventDefault();
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
      const text = e.clipboardData.getData("text/plain");
      if (!text) return;
      e.preventDefault();
      const { row, col } = sel.focus;
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
    [editing, readOnly, sel.focus, setCell, bulkUpdate]
  );

  const handleCopy = useCallback(
    (e: ClipboardEvent<HTMLDivElement>) => {
      if (editing) return;
      // Range selections copy the rectangle as TSV (Sheets/Excel
      // convention). Column/row selections copy just the active cell —
      // serializing an entire column would be unbounded.
      if (sel.mode === "range") {
        const { r1, r2, c1, c2 } = selBox;
        const lines: string[] = [];
        for (let r = r1; r <= r2; r++) {
          const cols: string[] = [];
          for (let c = c1; c <= c2; c++) {
            const v = cells.get(keyOf(r, c));
            cols.push(v == null ? "" : String(v));
          }
          lines.push(cols.join("\t"));
        }
        const text = lines.join("\n");
        if (text === "") return;
        e.preventDefault();
        e.clipboardData.setData("text/plain", text);
        return;
      }
      const value = cells.get(keyOf(sel.focus.row, sel.focus.col));
      if (value == null) return;
      e.preventDefault();
      e.clipboardData.setData("text/plain", String(value));
    },
    [editing, cells, sel.mode, sel.focus, selBox]
  );

  const handleExportCsv = useCallback(() => {
    try {
      const csv = cellsToCsv(cells);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      downloadBlob(blob, `${slugify(documentTitle)}.csv`);
      toast.success(t("documents:spreadsheet.exportSuccess"));
    } catch {
      toast.error(t("documents:spreadsheet.exportError"));
    }
  }, [cells, documentTitle, t]);

  const handleExportXlsx = useCallback(async () => {
    try {
      const blob = await cellsToXlsx(cells, formatting, documentTitle);
      downloadBlob(blob, `${slugify(documentTitle)}.xlsx`);
      toast.success(t("documents:spreadsheet.exportSuccess"));
    } catch {
      toast.error(t("documents:spreadsheet.exportError"));
    }
  }, [cells, formatting, documentTitle, t]);

  const handleImportClick = useCallback(() => {
    if (readOnly) return;
    fileInputRef.current?.click();
  }, [readOnly]);

  const handleFileSelected = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      const MAX_BYTES = 50 * 1024 * 1024;
      if (file.size > MAX_BYTES) {
        toast.error(t("documents:spreadsheet.fileTooLarge"));
        return;
      }
      const isXlsx =
        file.name.toLowerCase().endsWith(".xlsx") ||
        file.type === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
      try {
        if (isXlsx) {
          const buffer = await file.arrayBuffer();
          const parsed = await xlsxToContent(buffer);
          if (
            Object.keys(parsed.cells).length === 0 &&
            Object.keys(parsed.formatting.columns).length === 0 &&
            Object.keys(parsed.formatting.rows).length === 0 &&
            Object.keys(parsed.formatting.cellStyles).length === 0
          ) {
            toast.error(t("documents:spreadsheet.importEmpty"));
            return;
          }
          if (parsed.sheetCount > 1) {
            toast.info(t("documents:spreadsheet.multiSheetWarning"));
          }
          setPendingImport({
            cells: parsed.cells,
            rows: parsed.dimensions.rows,
            cols: parsed.dimensions.cols,
            formatting: parsed.formatting,
          });
          return;
        }
        const text = await file.text();
        const parsed = csvToCells(text);
        if (Object.keys(parsed.cells).length === 0) {
          toast.error(t("documents:spreadsheet.importEmpty"));
          return;
        }
        setPendingImport(parsed);
      } catch {
        toast.error(t("documents:spreadsheet.importParseError"));
      }
    },
    [t]
  );

  const confirmImport = useCallback(() => {
    if (!pendingImport) return;
    const dims = {
      rows: Math.min(Math.max(pendingImport.rows, DEFAULT_ROWS), MAX_ROWS),
      cols: Math.min(Math.max(pendingImport.cols, DEFAULT_COLS), MAX_COLS),
    };
    const fmt = pendingImport.formatting;
    if (fmt) {
      // xlsx: replace cells AND formatting in one transaction so peers
      // never observe a torn state (new cells, old formatting) and the
      // whole import is a single undo step. Yjs flattens the nested
      // transacts in each replaceAll into this outer one.
      docForData.transact(() => {
        replaceAll(pendingImport.cells, dims);
        formatting.replaceAll(fmt);
      }, "spreadsheet-import");
    } else {
      // csv: cells only — formatting is intentionally left untouched so
      // the CSV path stays byte-for-byte the pre-formatting behavior.
      replaceAll(pendingImport.cells, dims);
    }
    setPendingImport(null);
    toast.success(t("documents:spreadsheet.importSuccess"));
  }, [pendingImport, replaceAll, formatting, docForData, t]);

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
  const scrollTop = rowVirtualizer.scrollOffset ?? 0;
  const scrollLeft = colVirtualizer.scrollOffset ?? 0;

  const renderCell = useCallback(
    (r: number, c: number, left: number, top: number) => {
      const isActive = sel.focus.row === r && sel.focus.col === c;
      const isEditing = editing?.row === r && editing?.col === c;
      const value = cells.get(keyOf(r, c));
      const numberFormat = resolveCellFormat(r, c, formatting);
      const display = isEditing ? "" : value == null ? "" : formatCellValue(value, numberFormat);
      const isBoolean = typeof value === "boolean" && !numberFormat;
      const peer = peerSelectionsByCell.get(keyOf(r, c));
      const cellCss = styleToCss(resolveCellStyle(r, c, formatting));
      // A red/redParens negative number wins over any explicit text
      // color (Excel's numFmt color section overrides the font color).
      if (negativeRendersRed(value ?? null, numberFormat)) cellCss.color = "#dc2626";
      return (
        <CellView
          key={keyOf(r, c)}
          style={{ left, top, width: colWidth(c), height: rowHeight(r) }}
          cellCss={cellCss}
          isActive={isActive}
          inSelection={isInSel(r, c)}
          isEditing={Boolean(isEditing)}
          display={display}
          booleanValue={isBoolean ? (value as boolean) : null}
          readOnly={readOnly}
          draft={isEditing ? editing!.draft : ""}
          inputRef={isEditing ? editingInputRef : null}
          peerColor={peer?.selection.color ?? null}
          peerName={peer?.user.name ?? null}
          onMouseDown={(e) => {
            if (isEditing) return;
            if (e.button !== 0) return;
            containerRef.current?.focus();
            selectingRef.current = "range";
            selectCell(r, c, e.shiftKey);
          }}
          onMouseEnter={() => {
            if (selectingRef.current !== "range") return;
            setSel((p) => ({
              anchor: p.anchor,
              focus: { row: r, col: c },
              mode: "range",
            }));
          }}
          onDoubleClick={() => beginEdit(r, c)}
          onToggleBoolean={() => {
            if (readOnly || !isBoolean) return;
            selectCell(r, c);
            setCell(r, c, !(value as boolean));
          }}
          onDraftChange={(draft) => setEditing({ row: r, col: c, draft })}
          onEditingKeyDown={handleEditingKeyDown}
          onEditingBlur={() => commitEdit()}
        />
      );
    },
    [
      cells,
      formatting,
      sel.focus,
      isInSel,
      editing,
      readOnly,
      peerSelectionsByCell,
      colWidth,
      rowHeight,
      selectCell,
      beginEdit,
      setCell,
      handleEditingKeyDown,
      commitEdit,
    ]
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
          onExportCsv={handleExportCsv}
          onExportXlsx={handleExportXlsx}
          onImport={handleImportClick}
          onUndo={history.undo}
          onRedo={history.redo}
          canUndo={history.canUndo}
          canRedo={history.canRedo}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="hidden"
          onChange={handleFileSelected}
        />
      </div>

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
            {virtualCols.map((col) => (
              <button
                type="button"
                key={`colh-${col.index}`}
                onMouseDown={(e) => {
                  if (e.button !== 0) return;
                  containerRef.current?.focus();
                  selectingRef.current = "columns";
                  selectColumn(col.index, e.shiftKey);
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
            ))}
          </div>

          {/* Row-header strip — sticky left keeps numbers glued while
              scrolling horizontally. */}
          <div
            className="sticky left-0 z-10 bg-muted"
            style={{ width: ROW_HEADER_WIDTH, height: totalGridHeight }}
          >
            {virtualRows.map((row) => (
              <button
                type="button"
                key={`rowh-${row.index}`}
                onMouseDown={(e) => {
                  if (e.button !== 0) return;
                  containerRef.current?.focus();
                  selectingRef.current = "rows";
                  selectRow(row.index, e.shiftKey);
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
            ))}
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

          {/* Frozen rows band — pinned just below the column header,
              scrolls horizontally with the body. */}
          {frozenRows > 0 && (
            <div
              className="absolute bg-background"
              style={{
                left: ROW_HEADER_WIDTH,
                top: COL_HEADER_HEIGHT + scrollTop,
                width: totalGridWidth,
                height: frozenBandHeight,
                zIndex: 6,
              }}
            >
              {virtualCols.map((col) =>
                col.index < frozenCols
                  ? null
                  : Array.from({ length: frozenRows }, (_, r) =>
                      renderCell(r, col.index, col.start, prefixRow[r])
                    )
              )}
            </div>
          )}

          {/* Frozen cols band — pinned right of the row header, scrolls
              vertically with the body. */}
          {frozenCols > 0 && (
            <div
              className="absolute bg-background"
              style={{
                left: ROW_HEADER_WIDTH + scrollLeft,
                top: COL_HEADER_HEIGHT,
                width: frozenBandWidth,
                height: totalGridHeight,
                zIndex: 5,
              }}
            >
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
              className="absolute bg-background"
              style={{
                left: ROW_HEADER_WIDTH + scrollLeft,
                top: COL_HEADER_HEIGHT + scrollTop,
                width: frozenBandWidth,
                height: frozenBandHeight,
                zIndex: 7,
              }}
            >
              {Array.from({ length: frozenRows }, (_, r) =>
                Array.from({ length: frozenCols }, (_, c) =>
                  renderCell(r, c, prefixCol[c], prefixRow[r])
                )
              )}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={pendingImport !== null}
        onOpenChange={(open) => {
          if (!open) setPendingImport(null);
        }}
        title={t("documents:spreadsheet.importConfirmTitle")}
        description={t("documents:spreadsheet.importConfirmDescription")}
        confirmLabel={t("documents:spreadsheet.importConfirmAction")}
        onConfirm={confirmImport}
        destructive
      />
    </div>
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
  isEditing: boolean;
  display: string;
  booleanValue: boolean | null;
  readOnly: boolean;
  draft: string;
  inputRef: React.RefObject<HTMLInputElement | null> | null;
  peerColor: string | null;
  peerName: string | null;
  onMouseDown: (e: React.MouseEvent) => void;
  onMouseEnter: () => void;
  onDoubleClick: () => void;
  onToggleBoolean: () => void;
  onDraftChange: (draft: string) => void;
  onEditingKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  onEditingBlur: () => void;
}

const CellView = ({
  style,
  cellCss,
  isActive,
  inSelection,
  isEditing,
  display,
  booleanValue,
  readOnly,
  draft,
  inputRef,
  peerColor,
  peerName,
  onMouseDown,
  onMouseEnter,
  onDoubleClick,
  onToggleBoolean,
  onDraftChange,
  onEditingKeyDown,
  onEditingBlur,
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

  if (isEditing) {
    return (
      <div className={baseClass} style={containerStyle}>
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={onEditingKeyDown}
          onBlur={onEditingBlur}
          className="h-full w-full select-text bg-background px-1.5 outline-none"
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
        {peerOverlay}
      </div>
    );
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: cell is part of a role="grid" widget; keyboard/selection is owned by the container
    <div
      className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
      style={containerStyle}
      onMouseDown={onMouseDown}
      onMouseEnter={onMouseEnter}
      onDoubleClick={onDoubleClick}
    >
      <span className="w-full truncate">{display}</span>
      {selectionOverlay}
      {peerOverlay}
    </div>
  );
};
