import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";

import { type CellValue, keyOf } from "@/lib/spreadsheet/coords";

/**
 * Backing store for the spreadsheet's cell map and grid dimensions.
 *
 * When ``yDoc`` is non-null:
 *   - cells live in a ``Y.Map<unknown>`` named ``"cells"`` on the doc.
 *   - dimensions live in a ``Y.Map<unknown>`` named ``"meta"`` (under
 *     keys ``"rows"`` / ``"cols"``).
 *   - Local writes broadcast to peers, remote writes flow back through
 *     ``observe`` and update the React mirror.
 *
 * When ``yDoc`` is null (collab disabled, offline, or ``readOnly``
 * viewer), both fall back to plain React state so the editor still
 * works exactly as it did pre-collaboration.
 *
 * Multi-cell operations (paste, CSV import, bulk clear) wrap their
 * writes in ``yDoc.transact(...)`` so peers receive a single update
 * event instead of one per cell. ``replaceAll`` writes both the cells
 * AND the new dimensions inside the same transaction so a shrinking
 * import doesn't leave peers stuck on the old grid size.
 */
export interface SpreadsheetCellsStore {
  cells: Map<string, CellValue>;
  dimensions: { rows: number; cols: number };
  setCell: (row: number, col: number, value: CellValue) => void;
  setDimensions: (next: { rows: number; cols: number }) => void;
  bulkUpdate: (mutator: (draft: Map<string, CellValue>) => void) => void;
  replaceAll: (
    nextCells: Record<string, CellValue>,
    nextDimensions: { rows: number; cols: number }
  ) => void;
}

const Y_CELLS_KEY = "cells";
const Y_META_KEY = "meta";
const META_ROWS = "rows";
const META_COLS = "cols";

const cellsMapToObject = (cells: Map<string, CellValue>): Record<string, CellValue> => {
  const out: Record<string, CellValue> = {};
  for (const [key, value] of cells) out[key] = value;
  return out;
};

const writeToYMap = (
  yMap: Y.Map<unknown>,
  next: Map<string, CellValue>,
  prev: Map<string, CellValue>
) => {
  // Diff against ``prev`` so we only emit ops for actually-changed
  // cells. Otherwise the observer on the other end would see N writes
  // even when most were unchanged, which inflates the snapshot history
  // and can cause flicker.
  for (const [key, value] of next) {
    if (prev.get(key) !== value) yMap.set(key, value);
  }
  for (const key of prev.keys()) {
    if (!next.has(key)) yMap.delete(key);
  }
};

/**
 * Build a Map<string, CellValue> from a Y.Map. Filters out anything
 * that isn't a primitive scalar — defends against malformed remote
 * state from a peer running an older / future client.
 */
const yMapToCellsMap = (yMap: Y.Map<unknown>): Map<string, CellValue> => {
  const out = new Map<string, CellValue>();
  yMap.forEach((value, key) => {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean" ||
      value === null
    ) {
      out.set(key, value as CellValue);
    }
  });
  return out;
};

const readMetaDimensions = (
  yMeta: Y.Map<unknown>,
  fallback: { rows: number; cols: number }
): { rows: number; cols: number } => {
  const rowsValue = yMeta.get(META_ROWS);
  const colsValue = yMeta.get(META_COLS);
  return {
    rows:
      typeof rowsValue === "number" && Number.isFinite(rowsValue) && rowsValue > 0
        ? rowsValue
        : fallback.rows,
    cols:
      typeof colsValue === "number" && Number.isFinite(colsValue) && colsValue > 0
        ? colsValue
        : fallback.cols,
  };
};

interface UseSpreadsheetCellsArgs {
  yDoc: Y.Doc | null;
  initialCells: Record<string, CellValue>;
  initialDimensions: { rows: number; cols: number };
}

export const useSpreadsheetCells = ({
  yDoc,
  initialCells,
  initialDimensions,
}: UseSpreadsheetCellsArgs): SpreadsheetCellsStore => {
  // The Y.Map handles (when collaborating) or null (local-only).
  const yMap = useMemo<Y.Map<unknown> | null>(
    () => (yDoc ? (yDoc.getMap(Y_CELLS_KEY) as Y.Map<unknown>) : null),
    [yDoc]
  );
  const yMeta = useMemo<Y.Map<unknown> | null>(
    () => (yDoc ? (yDoc.getMap(Y_META_KEY) as Y.Map<unknown>) : null),
    [yDoc]
  );

  // Local mirror of the cell map. When collaborating, this is rebuilt
  // from the Y.Map after every observed event; when not, it's the
  // canonical store.
  const [cells, setCells] = useState<Map<string, CellValue>>(() => {
    if (yMap && yMap.size > 0) return yMapToCellsMap(yMap);
    return new Map(Object.entries(initialCells));
  });
  const [dimensions, setDimensionsState] = useState<{ rows: number; cols: number }>(() => {
    if (yMeta && (yMeta.get(META_ROWS) !== undefined || yMeta.get(META_COLS) !== undefined)) {
      return readMetaDimensions(yMeta, initialDimensions);
    }
    return initialDimensions;
  });

  // One-shot bootstrap into a fresh Y.Doc: when we first attach to a
  // Y.Map that's empty (no peers have written yet, no persisted yjs
  // snapshot), seed it with the JSON-snapshot cells AND dimensions so
  // the local editor and peers start from the same content.
  //
  // The ref tracks *which* Y.Doc was bootstrapped against, not just
  // whether we've ever bootstrapped. A boolean would persist across a
  // provider reconnect that swaps in a new Y.Doc — the new (empty) Map
  // would never get seeded from initialCells and the spreadsheet would
  // render blank until a peer wrote or yjs_state was restored.
  const bootstrappedDocRef = useRef<Y.Doc | null>(null);
  useEffect(() => {
    if (!yDoc || !yMap || !yMeta) return;
    if (bootstrappedDocRef.current === yDoc) return;
    const metaSeeded = yMeta.get(META_ROWS) !== undefined || yMeta.get(META_COLS) !== undefined;
    const cellsSeeded = yMap.size > 0;
    if (cellsSeeded || metaSeeded) {
      // Y.Doc already has content (from yjs_state load or another
      // peer) — adopt it and skip the seed.
      if (cellsSeeded) setCells(yMapToCellsMap(yMap));
      if (metaSeeded) setDimensionsState(readMetaDimensions(yMeta, initialDimensions));
      bootstrappedDocRef.current = yDoc;
      return;
    }
    yDoc.transact(() => {
      for (const [key, value] of Object.entries(initialCells)) yMap.set(key, value);
      yMeta.set(META_ROWS, initialDimensions.rows);
      yMeta.set(META_COLS, initialDimensions.cols);
    }, "spreadsheet-bootstrap");
    bootstrappedDocRef.current = yDoc;
  }, [yDoc, yMap, yMeta, initialCells, initialDimensions]);

  // Subscribe to remote cell changes. ``transaction.local`` is true
  // for edits that originated in this client; we still rebuild the
  // local mirror because our ``setCells`` lives outside the Y.Map and
  // needs to reflect every committed change.
  useEffect(() => {
    if (!yMap) return;
    const handler = () => setCells(yMapToCellsMap(yMap));
    yMap.observe(handler);
    return () => yMap.unobserve(handler);
  }, [yMap]);

  // Subscribe to remote dimension changes (e.g. a peer's CSV import
  // shrunk the grid).
  useEffect(() => {
    if (!yMeta) return;
    const handler = () =>
      setDimensionsState((prev) => {
        const next = readMetaDimensions(yMeta, prev);
        if (next.rows === prev.rows && next.cols === prev.cols) return prev;
        return next;
      });
    yMeta.observe(handler);
    return () => yMeta.unobserve(handler);
  }, [yMeta]);

  const setCell = useCallback(
    (row: number, col: number, value: CellValue) => {
      const key = keyOf(row, col);
      if (yMap && yDoc) {
        yDoc.transact(() => {
          if (value === null || value === "") yMap.delete(key);
          else yMap.set(key, value);
        }, "spreadsheet-edit");
        return;
      }
      setCells((prev) => {
        const next = new Map(prev);
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
        return next;
      });
    },
    [yDoc, yMap]
  );

  const setDimensions = useCallback(
    (next: { rows: number; cols: number }) => {
      if (yMeta && yDoc) {
        yDoc.transact(() => {
          yMeta.set(META_ROWS, next.rows);
          yMeta.set(META_COLS, next.cols);
        }, "spreadsheet-dimensions");
        return;
      }
      setDimensionsState((prev) =>
        prev.rows === next.rows && prev.cols === next.cols ? prev : next
      );
    },
    [yDoc, yMeta]
  );

  const bulkUpdate = useCallback(
    (mutator: (draft: Map<string, CellValue>) => void) => {
      if (yMap && yDoc) {
        // Compute the next state outside the Y transaction so the
        // mutator's logic doesn't need to know about Y.Map semantics,
        // then diff-apply inside one transaction so peers receive a
        // single update.
        const prev = yMapToCellsMap(yMap);
        const next = new Map(prev);
        mutator(next);
        yDoc.transact(() => writeToYMap(yMap, next, prev), "spreadsheet-bulk");
        return;
      }
      setCells((prev) => {
        const next = new Map(prev);
        mutator(next);
        return next;
      });
    },
    [yDoc, yMap]
  );

  const replaceAll = useCallback(
    (nextCells: Record<string, CellValue>, nextDimensions: { rows: number; cols: number }) => {
      if (yMap && yMeta && yDoc) {
        yDoc.transact(() => {
          // Clear and re-populate cells.
          for (const key of Array.from(yMap.keys())) yMap.delete(key);
          for (const [key, value] of Object.entries(nextCells)) yMap.set(key, value);
          // Broadcast new dimensions atomically with the cells so peers
          // don't transiently see (new cells, old dimensions).
          yMeta.set(META_ROWS, nextDimensions.rows);
          yMeta.set(META_COLS, nextDimensions.cols);
        }, "spreadsheet-replace-all");
        return;
      }
      setCells(new Map(Object.entries(nextCells)));
      setDimensionsState(nextDimensions);
    },
    [yDoc, yMap, yMeta]
  );

  return { cells, dimensions, setCell, setDimensions, bulkUpdate, replaceAll };
};

export const exportCellsToJsonObject = cellsMapToObject;
