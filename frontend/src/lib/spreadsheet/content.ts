/**
 * The persisted shape of a spreadsheet document, and the parser that
 * hydrates it.
 *
 * ``Document.content`` holds a JSON snapshot of the whole workbook — the
 * live state is a set of Y.Maps synced over the collaboration provider, and
 * this is what the autosave PATCH writes. The backend normalizer in
 * ``backend/app/services/tenant/documents_spreadsheet.py`` validates the
 * same shape; keep the two in step.
 *
 * Schema versions
 * ---------------
 * * **v1**: ``{schema_version, kind, dimensions, cells}`` — one sheet, no
 *   formatting.
 * * **v2**: adds ``columns`` / ``rows`` / ``cellStyles`` / ``frozen``, still
 *   one sheet.
 * * **v3** (current): ``{schema_version, kind, sheets: [...]}`` — the whole
 *   workbook, each entry carrying what a v2 payload carried plus an ``id``
 *   and a ``name``.
 *
 * {@link parseSpreadsheetContent} accepts all three and always returns v3,
 * so a document written before multi-sheet opens as a one-sheet workbook
 * with no migration step.
 */

import type { CellValue } from "@/lib/spreadsheet/coords";
import {
  DEFAULT_SHEET_ID,
  MAX_SHEETS,
  newSheetId,
  type SheetId,
  sanitizeSheetName,
  uniqueSheetName,
} from "@/lib/spreadsheet/sheets";
import {
  type CellFmt,
  type ColumnFmt,
  type RowFmt,
  type SpreadsheetFormatting,
  sanitizeFormatting,
} from "@/lib/spreadsheet/styles";

export const SPREADSHEET_SCHEMA_VERSION = 3;

export const DEFAULT_ROWS = 100;
export const DEFAULT_COLS = 26;
export const MAX_ROWS = 100_000;
export const MAX_COLS = 1_000;

/** One sheet's persisted content: identity, canvas size, and the same
 *  sparse structures a v2 document stored at its top level. */
export interface SpreadsheetSheetContent {
  id: SheetId;
  name: string;
  dimensions: { rows: number; cols: number };
  cells: Record<string, CellValue>;
  columns: Record<string, ColumnFmt>;
  rows: Record<string, RowFmt>;
  cellStyles: Record<string, CellFmt>;
  frozen: { rows: number; cols: number };
}

export interface SpreadsheetContent {
  schema_version: number;
  kind: "spreadsheet";
  sheets: SpreadsheetSheetContent[];
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const clampDim = (value: unknown, fallback: number, max: number): number => {
  const n = typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : fallback;
  return Math.min(Math.max(n, fallback), max);
};

/** Keep only the scalar entries under canonical ``"r:c"`` keys. Mirrors the
 *  backend's key canonicalization so ``"01:2"`` and ``"1:2"`` can't both
 *  survive into the Y.Map as separate cells. */
const sanitizeCells = (raw: unknown): Record<string, CellValue> => {
  const out: Record<string, CellValue> = {};
  if (!isRecord(raw)) return out;
  for (const [key, value] of Object.entries(raw)) {
    const m = /^(\d+):(\d+)$/.exec(key);
    if (!m) continue;
    if (value === null || value === "") continue;
    if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean")
      continue;
    out[`${Number(m[1])}:${Number(m[2])}`] = value;
  }
  return out;
};

const boundsOf = (cells: Record<string, CellValue>): { rows: number; cols: number } => {
  let rows = 0;
  let cols = 0;
  for (const key of Object.keys(cells)) {
    const colon = key.indexOf(":");
    rows = Math.max(rows, Number(key.slice(0, colon)) + 1);
    cols = Math.max(cols, Number(key.slice(colon + 1)) + 1);
  }
  return { rows, cols };
};

/**
 * Read one sheet out of a payload slice — the same call handles a v3
 * ``sheets[i]`` entry and a v1/v2 document's top level, which is exactly
 * the upcast: the old shape *is* a sheet, it just never said so.
 */
const parseSheet = (
  raw: unknown,
  fallbackId: SheetId,
  fallbackName: string
): SpreadsheetSheetContent => {
  const src = isRecord(raw) ? raw : {};
  const cells = sanitizeCells(src.cells);
  const bounds = boundsOf(cells);
  const dims = isRecord(src.dimensions) ? src.dimensions : {};
  const formatting: SpreadsheetFormatting = sanitizeFormatting(src);
  return {
    id: typeof src.id === "string" && src.id ? src.id : fallbackId,
    name: sanitizeSheetName(typeof src.name === "string" ? src.name : "") || fallbackName,
    dimensions: {
      rows: clampDim(dims.rows, Math.max(DEFAULT_ROWS, bounds.rows), MAX_ROWS),
      cols: clampDim(dims.cols, Math.max(DEFAULT_COLS, bounds.cols), MAX_COLS),
    },
    cells,
    columns: formatting.columns,
    rows: formatting.rows,
    cellStyles: formatting.cellStyles,
    frozen: formatting.frozen,
  };
};

/** A brand-new, empty workbook: one sheet, default canvas. */
export const emptySpreadsheetContent = (): SpreadsheetContent => ({
  schema_version: SPREADSHEET_SCHEMA_VERSION,
  kind: "spreadsheet",
  sheets: [parseSheet(undefined, DEFAULT_SHEET_ID, "Sheet1")],
});

/**
 * Coerce an arbitrary ``document.content`` blob into the canonical v3
 * workbook. Never throws — the backend is the authority on hard rejects,
 * the client stays forgiving — and never returns zero sheets, because an
 * editor with no sheet to show has nothing to render.
 *
 * Sheet ids and names are made unique here rather than trusted: a duplicate
 * name would make ``=Sheet2!A1`` ambiguous, and a duplicate id would make
 * two tabs share one Yjs container.
 */
export const parseSpreadsheetContent = (raw: unknown): SpreadsheetContent => {
  const src = isRecord(raw) ? raw : {};
  const rawSheets = Array.isArray(src.sheets) ? src.sheets.slice(0, MAX_SHEETS) : null;
  // v1 / v2: the document's top level is the one and only sheet.
  const entries = rawSheets && rawSheets.length > 0 ? rawSheets : [src];

  const seenIds = new Set<SheetId>();
  const names: string[] = [];
  const sheets = entries.map((entry, index) => {
    const sheet = parseSheet(
      entry,
      index === 0 ? DEFAULT_SHEET_ID : newSheetId(),
      `Sheet${index + 1}`
    );
    if (seenIds.has(sheet.id)) sheet.id = newSheetId();
    seenIds.add(sheet.id);
    sheet.name = uniqueSheetName(sheet.name, names);
    names.push(sheet.name);
    return sheet;
  });

  return { schema_version: SPREADSHEET_SCHEMA_VERSION, kind: "spreadsheet", sheets };
};
