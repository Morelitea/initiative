import { useVirtualizer } from "@tanstack/react-virtual";
import { Download, Upload } from "lucide-react";
import {
  type ChangeEvent,
  type CSSProperties,
  type KeyboardEvent,
  type ClipboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { type CellValue, colIndexToLetter, keyOf } from "@/lib/spreadsheet/coords";
import {
  cellsToCsv,
  coerceScalar,
  csvToCells,
  detectClipboardDelimiter,
  offsetCells,
} from "@/lib/spreadsheet/csv";
import { cn } from "@/lib/utils";

export interface SpreadsheetContent {
  schema_version: 1;
  kind: "spreadsheet";
  dimensions: { rows: number; cols: number };
  cells: Record<string, CellValue>;
}

interface SpreadsheetDocumentEditorProps {
  initialContent: SpreadsheetContent;
  onContentChange: (content: SpreadsheetContent) => void;
  documentTitle: string;
  readOnly: boolean;
  className?: string;
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
    schema_version: 1,
    kind: "spreadsheet",
    dimensions: {
      rows: Math.min(Math.max(requestedRows, DEFAULT_ROWS), MAX_ROWS),
      cols: Math.min(Math.max(requestedCols, DEFAULT_COLS), MAX_COLS),
    },
    cells,
  };
};

export const SpreadsheetDocumentEditor = ({
  initialContent,
  onContentChange,
  documentTitle,
  readOnly,
  className,
}: SpreadsheetDocumentEditorProps) => {
  const { t } = useTranslation(["documents", "common"]);

  const [cells, setCells] = useState<Map<string, CellValue>>(() => {
    const sanitized = sanitizeContent(initialContent);
    return new Map(Object.entries(sanitized.cells));
  });
  const [dimensions, setDimensions] = useState<{ rows: number; cols: number }>(() => {
    return sanitizeContent(initialContent).dimensions;
  });
  const [selected, setSelected] = useState<{ row: number; col: number }>({ row: 0, col: 0 });
  const [editing, setEditing] = useState<{ row: number; col: number; draft: string } | null>(null);
  const [pendingImport, setPendingImport] = useState<{
    cells: Record<string, CellValue>;
    rows: number;
    cols: number;
  } | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const editingInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Keep parent in sync. Wrapped so callers don't have to think about
  // building the snapshot shape.
  const emitContent = useCallback(
    (nextCells: Map<string, CellValue>, nextDims: { rows: number; cols: number }) => {
      const cellsObj: Record<string, CellValue> = {};
      for (const [key, value] of nextCells) cellsObj[key] = value;
      onContentChange({
        schema_version: 1,
        kind: "spreadsheet",
        dimensions: nextDims,
        cells: cellsObj,
      });
    },
    [onContentChange]
  );

  const updateCells = useCallback(
    (mutator: (draft: Map<string, CellValue>) => void) => {
      // Build the next cell map and dimensions OUTSIDE any state
      // updater so we don't run side effects (setDimensions,
      // emitContent) inside one. React's Strict Mode invokes updaters
      // twice in development to surface impurity; doing the side
      // effects here means each user edit emits onContentChange exactly
      // once and the autosave only PATCHes once.
      const next = new Map(cells);
      mutator(next);
      let maxRow = dimensions.rows - 1;
      let maxCol = dimensions.cols - 1;
      for (const key of next.keys()) {
        const colon = key.indexOf(":");
        if (colon < 0) continue;
        const r = Number(key.slice(0, colon));
        const c = Number(key.slice(colon + 1));
        if (r > maxRow) maxRow = r;
        if (c > maxCol) maxCol = c;
      }
      const nextDims = {
        rows: Math.min(Math.max(maxRow + 1, dimensions.rows), MAX_ROWS),
        cols: Math.min(Math.max(maxCol + 1, dimensions.cols), MAX_COLS),
      };
      setCells(next);
      if (nextDims.rows !== dimensions.rows || nextDims.cols !== dimensions.cols) {
        setDimensions(nextDims);
      }
      emitContent(next, nextDims);
    },
    [cells, dimensions, emitContent]
  );

  const setCell = useCallback(
    (row: number, col: number, value: CellValue) => {
      const key = keyOf(row, col);
      updateCells((draft) => {
        if (value === null || value === "") {
          draft.delete(key);
        } else {
          draft.set(key, value);
        }
      });
    },
    [updateCells]
  );

  const rowVirtualizer = useVirtualizer({
    count: dimensions.rows,
    getScrollElement: () => containerRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5,
  });

  const colVirtualizer = useVirtualizer({
    count: dimensions.cols,
    getScrollElement: () => containerRef.current,
    estimateSize: () => COL_WIDTH,
    horizontal: true,
    overscan: 3,
  });

  // Auto-grow the canvas when scrolling near the edge so the grid feels
  // unbounded. We never shrink — empty rows / cols are cheap.
  const virtualRows = rowVirtualizer.getVirtualItems();
  const virtualCols = colVirtualizer.getVirtualItems();
  useEffect(() => {
    if (virtualRows.length === 0) return;
    const lastRow = virtualRows[virtualRows.length - 1].index;
    if (lastRow >= dimensions.rows - GROW_THRESHOLD && dimensions.rows < MAX_ROWS) {
      setDimensions((d) => ({
        ...d,
        rows: Math.min(d.rows + ROW_GROWTH_STEP, MAX_ROWS),
      }));
    }
  }, [virtualRows, dimensions.rows]);
  useEffect(() => {
    if (virtualCols.length === 0) return;
    const lastCol = virtualCols[virtualCols.length - 1].index;
    if (lastCol >= dimensions.cols - GROW_THRESHOLD && dimensions.cols < MAX_COLS) {
      setDimensions((d) => ({
        ...d,
        cols: Math.min(d.cols + COL_GROWTH_STEP, MAX_COLS),
      }));
    }
  }, [virtualCols, dimensions.cols]);

  const moveSelection = useCallback((dRow: number, dCol: number) => {
    setSelected((prev) => {
      const row = Math.max(0, Math.min(prev.row + dRow, MAX_ROWS - 1));
      const col = Math.max(0, Math.min(prev.col + dCol, MAX_COLS - 1));
      return { row, col };
    });
  }, []);

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
      if (next) setSelected(next);
    },
    [editing, setCell]
  );

  const cancelEdit = useCallback(() => {
    setEditing(null);
  }, []);

  // Focus the inline input when entering edit mode. Keyed on the cell
  // coordinates, NOT the full ``editing`` object — including ``draft``
  // in the dependency would re-run the effect on every keystroke. We
  // intentionally don't ``.select()`` the input: when edit mode is
  // entered by typing a character, the draft is already that one
  // character, and selecting it would let the next keystroke overwrite
  // it. ``focus()`` alone leaves the cursor at the end of the existing
  // value, which matches Numbers / Excel / Sheets behavior.
  const editingCellKey = editing ? `${editing.row}:${editing.col}` : null;
  useEffect(() => {
    if (editingCellKey && editingInputRef.current) {
      editingInputRef.current.focus();
    }
  }, [editingCellKey]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (editing) return; // input handles its own keys
      if (readOnly) return;
      const { row, col } = selected;
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          moveSelection(1, 0);
          return;
        case "ArrowUp":
          e.preventDefault();
          moveSelection(-1, 0);
          return;
        case "ArrowRight":
          e.preventDefault();
          moveSelection(0, 1);
          return;
        case "ArrowLeft":
          e.preventDefault();
          moveSelection(0, -1);
          return;
        case "Enter":
        case "F2":
          e.preventDefault();
          beginEdit(row, col);
          return;
        case "Backspace":
        case "Delete":
          e.preventDefault();
          setCell(row, col, null);
          return;
        case "Tab":
          e.preventDefault();
          moveSelection(0, e.shiftKey ? -1 : 1);
          return;
      }
      // Printable character → enter edit mode with that character.
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        beginEdit(row, col, e.key);
      }
    },
    [editing, readOnly, selected, moveSelection, beginEdit, setCell]
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
      const { row, col } = selected;
      // Single-cell value: skip the CSV parse.
      if (!text.includes("\n") && !text.includes("\t") && !text.includes(",")) {
        setCell(row, col, coerceScalar(text));
        return;
      }
      const delimiter = detectClipboardDelimiter(text);
      const parsed = csvToCells(text, { delimiter });
      const offset = offsetCells(parsed.cells, row, col);
      updateCells((draft) => {
        for (const [key, value] of Object.entries(offset)) draft.set(key, value);
      });
    },
    [editing, readOnly, selected, setCell, updateCells]
  );

  const handleCopy = useCallback(
    (e: ClipboardEvent<HTMLDivElement>) => {
      if (editing) return;
      const value = cells.get(keyOf(selected.row, selected.col));
      if (value == null) return;
      e.preventDefault();
      e.clipboardData.setData("text/plain", String(value));
    },
    [editing, cells, selected]
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

  const handleImportClick = useCallback(() => {
    if (readOnly) return;
    fileInputRef.current?.click();
  }, [readOnly]);

  const handleFileSelected = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-selecting the same file later
      if (!file) return;
      const MAX_BYTES = 50 * 1024 * 1024;
      if (file.size > MAX_BYTES) {
        toast.error(t("documents:spreadsheet.fileTooLarge"));
        return;
      }
      try {
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
    // Build outside any state updater — see `updateCells` comment.
    const next = new Map<string, CellValue>();
    for (const [key, value] of Object.entries(pendingImport.cells)) next.set(key, value);
    const nextDims = {
      rows: Math.min(Math.max(pendingImport.rows, DEFAULT_ROWS), MAX_ROWS),
      cols: Math.min(Math.max(pendingImport.cols, DEFAULT_COLS), MAX_COLS),
    };
    setCells(next);
    setDimensions(nextDims);
    emitContent(next, nextDims);
    setPendingImport(null);
    toast.success(t("documents:spreadsheet.importSuccess"));
  }, [pendingImport, emitContent, t]);

  const totalGridWidth = colVirtualizer.getTotalSize();
  const totalGridHeight = rowVirtualizer.getTotalSize();

  return (
    <div
      className={cn(
        "border-border bg-background flex flex-col overflow-hidden rounded-lg border",
        className
      )}
    >
      <div className="border-border bg-muted/40 flex items-center gap-2 border-b px-3 py-2 text-sm">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleExportCsv}
          className="gap-1.5"
        >
          <Download className="h-3.5 w-3.5" />
          {t("documents:spreadsheet.exportCsv")}
        </Button>
        {!readOnly && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleImportClick}
            className="gap-1.5"
          >
            <Upload className="h-3.5 w-3.5" />
            {t("documents:spreadsheet.importCsv")}
          </Button>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={handleFileSelected}
        />
        <div className="text-muted-foreground ml-auto font-mono text-xs">
          {colIndexToLetter(selected.col)}
          {selected.row + 1}
        </div>
      </div>

      <div
        ref={containerRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onCopy={handleCopy}
        className="focus-visible:outline-primary relative min-h-0 flex-1 overflow-auto focus:outline-none focus-visible:outline focus-visible:outline-2"
      >
        <div
          style={{
            width: ROW_HEADER_WIDTH + totalGridWidth,
            height: COL_HEADER_HEIGHT + totalGridHeight,
            position: "relative",
          }}
        >
          {/* Column-header strip — ``position: sticky; top: 0`` keeps
              column letters glued to the top of the scroll container as
              the user scrolls vertically. The strip is the full canvas
              width so its absolutely-positioned children line up with
              the cell columns horizontally. */}
          <div
            className="bg-muted sticky top-0 z-20"
            style={{
              left: 0,
              height: COL_HEADER_HEIGHT,
              width: ROW_HEADER_WIDTH + totalGridWidth,
            }}
          >
            {/* Top-left corner cap. Nested ``position: sticky; left: 0``
                inside the sticky-top strip pins it to both edges. */}
            <div
              className="border-border bg-muted sticky top-0 left-0 z-30 border-r border-b"
              style={{
                width: ROW_HEADER_WIDTH,
                height: COL_HEADER_HEIGHT,
              }}
            />
            {virtualCols.map((col) => (
              <div
                key={`colh-${col.index}`}
                className="border-border bg-muted text-muted-foreground absolute flex items-center justify-center border-r border-b font-mono text-xs"
                style={{
                  left: ROW_HEADER_WIDTH + col.start,
                  top: 0,
                  width: col.size,
                  height: COL_HEADER_HEIGHT,
                }}
              >
                {colIndexToLetter(col.index)}
              </div>
            ))}
          </div>

          {/* Row-header strip — ``position: sticky; left: 0`` keeps row
              numbers glued to the left of the scroll container as the
              user scrolls horizontally. The strip is the full canvas
              height (minus the column-header strip rendered above)
              so its absolutely-positioned children line up with cell
              rows vertically. */}
          <div
            className="sticky left-0 z-10"
            style={{
              // No ``top``: setting one on a position:sticky element
              // makes it stick vertically too (pinning to viewport-top
              // when its natural position would scroll above the
              // threshold), which would freeze the strip in place
              // while the absolutely-positioned row labels inside —
              // at ``top: row.start`` relative to the strip — slide
              // off-screen as scrollTop grows. Letting the strip flow
              // naturally below the column-header strip keeps row
              // labels aligned with the cells they describe and lets
              // the strip scroll vertically with the canvas.
              width: ROW_HEADER_WIDTH,
              height: totalGridHeight,
            }}
          >
            {virtualRows.map((row) => (
              <div
                key={`rowh-${row.index}`}
                className="border-border bg-muted text-muted-foreground absolute flex items-center justify-center border-r border-b font-mono text-xs"
                style={{
                  left: 0,
                  top: row.start,
                  width: ROW_HEADER_WIDTH,
                  height: row.size,
                }}
              >
                {row.index + 1}
              </div>
            ))}
          </div>

          {/* Cells */}
          {virtualRows.map((row) =>
            virtualCols.map((col) => {
              const isSelected = selected.row === row.index && selected.col === col.index;
              const isEditing = editing?.row === row.index && editing?.col === col.index;
              const value = cells.get(keyOf(row.index, col.index));
              const display = value == null ? "" : String(value);
              const isBoolean = typeof value === "boolean";
              const cellStyle: CSSProperties = {
                left: ROW_HEADER_WIDTH + col.start,
                top: COL_HEADER_HEIGHT + row.start,
                width: col.size,
                height: row.size,
              };
              return (
                <CellView
                  key={keyOf(row.index, col.index)}
                  style={cellStyle}
                  isSelected={isSelected}
                  isEditing={Boolean(isEditing)}
                  display={display}
                  booleanValue={isBoolean ? (value as boolean) : null}
                  readOnly={readOnly}
                  draft={isEditing ? editing!.draft : ""}
                  inputRef={isEditing ? editingInputRef : null}
                  onClick={() => {
                    if (isEditing) return;
                    setSelected({ row: row.index, col: col.index });
                  }}
                  onDoubleClick={() => beginEdit(row.index, col.index)}
                  onToggleBoolean={() => {
                    if (readOnly || !isBoolean) return;
                    setSelected({ row: row.index, col: col.index });
                    setCell(row.index, col.index, !(value as boolean));
                  }}
                  onDraftChange={(draft) => setEditing({ row: row.index, col: col.index, draft })}
                  onEditingKeyDown={handleEditingKeyDown}
                  onEditingBlur={() => commitEdit()}
                />
              );
            })
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
  isSelected: boolean;
  isEditing: boolean;
  display: string;
  /** When the cell value is a boolean, the actual ``true`` / ``false`` so
   *  we can render an interactive checkbox instead of "true" / "false"
   *  text. ``null`` for any non-boolean cell. */
  booleanValue: boolean | null;
  readOnly: boolean;
  draft: string;
  inputRef: React.RefObject<HTMLInputElement | null> | null;
  onClick: () => void;
  onDoubleClick: () => void;
  onToggleBoolean: () => void;
  onDraftChange: (draft: string) => void;
  onEditingKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  onEditingBlur: () => void;
}

const CellView = ({
  style,
  isSelected,
  isEditing,
  display,
  booleanValue,
  readOnly,
  draft,
  inputRef,
  onClick,
  onDoubleClick,
  onToggleBoolean,
  onDraftChange,
  onEditingKeyDown,
  onEditingBlur,
}: CellViewProps) => {
  const baseClass = useMemo(
    () =>
      cn(
        "border-border absolute box-border border-r border-b text-sm",
        isSelected && !isEditing && "ring-primary ring-2 ring-inset",
        isEditing && "ring-primary ring-2 ring-inset"
      ),
    [isSelected, isEditing]
  );

  if (isEditing) {
    return (
      <div className={baseClass} style={style}>
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={onEditingKeyDown}
          onBlur={onEditingBlur}
          className="bg-background h-full w-full px-1.5 outline-none"
        />
      </div>
    );
  }

  if (booleanValue !== null) {
    return (
      <div
        className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
        style={style}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
      >
        <Checkbox
          checked={booleanValue}
          disabled={readOnly}
          onClick={(e) => {
            // Stop the wrapper's onClick from firing twice (it would
            // also call onToggleBoolean via setCell). The wrapper still
            // sees the click for selection through the synthetic event
            // bubble — we just want the toggle to happen exactly once.
            e.stopPropagation();
            onToggleBoolean();
          }}
          aria-label={booleanValue ? "true" : "false"}
        />
      </div>
    );
  }

  return (
    <div
      className={cn(baseClass, "flex cursor-cell items-center px-1.5")}
      style={style}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
    >
      <span className="truncate">{display}</span>
    </div>
  );
};
