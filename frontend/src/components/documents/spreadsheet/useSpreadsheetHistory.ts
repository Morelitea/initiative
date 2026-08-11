import type * as Y from "yjs";

import { Y_SHEETS_KEY } from "@/components/documents/spreadsheet/workbookDoc";
import { useYjsHistory, type YjsHistory } from "@/hooks/useYjsHistory";

/**
 * Per-session undo/redo for the spreadsheet — a thin adapter over the
 * generic {@link useYjsHistory} primitive. The data hooks
 * (`useSpreadsheetCells` / `useSpreadsheetFormatting`) already funnel
 * every mutation through `doc.transact(fn, origin)`; this just tells
 * the shared `Y.UndoManager` which shared types and which origins
 * represent undoable user actions.
 */

// Every spreadsheet transaction origin that represents a user action.
// Bootstrap/seed origins ("spreadsheet-bootstrap",
// "spreadsheet-fmt-bootstrap") are intentionally excluded so hydrating
// a fresh doc is never undoable. CSV/XLSX import IS included so a
// fat-fingered import is a single undo step.
//
// IMPORTANT: an action that wraps several store mutations in an *outer*
// `doc.transact(fn, origin)` must list that OUTER origin here, not the
// inner store origins. Yjs flattens nested transacts and keeps only the
// outermost origin, so "spreadsheet-sort" / "spreadsheet-structure" (the
// sort and row/column insert/delete wrappers) are what the UndoManager
// actually sees — the inner "spreadsheet-bulk" / "spreadsheet-fmt-*"
// origins never surface for those ops.
const SPREADSHEET_UNDO_ORIGINS = [
  "spreadsheet-edit",
  "spreadsheet-bulk",
  "spreadsheet-replace-all",
  "spreadsheet-fmt-edit",
  "spreadsheet-fmt-batch",
  "spreadsheet-fmt-replace-all",
  "spreadsheet-import",
  "spreadsheet-sort",
  "spreadsheet-structure",
  "spreadsheet-sheet-add",
  "spreadsheet-sheet-rename",
  "spreadsheet-sheet-delete",
  "spreadsheet-sheet-move",
  "spreadsheet-sheet-duplicate",
] as const;

// Everything a spreadsheet owns hangs off the single `sheets` map (see
// `workbookDoc.ts`), and a `Y.UndoManager` tracks any type whose parent
// chain reaches a scoped one — so one entry covers every sheet's cells and
// formatting, including sheets created after the manager was built.
const spreadsheetScope = (doc: Y.Doc) => [doc.getMap(Y_SHEETS_KEY)];

export const useSpreadsheetHistory = (doc: Y.Doc | null): YjsHistory =>
  useYjsHistory({
    doc,
    getScope: spreadsheetScope,
    trackedOrigins: SPREADSHEET_UNDO_ORIGINS,
  });
