import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";

import { type CellValue, keyOf } from "@/lib/spreadsheet/coords";

/**
 * Backing store for the spreadsheet's cell map.
 *
 * When ``yDoc`` is non-null, cells live in a ``Y.Map<unknown>`` named
 * ``"cells"`` on the doc — local writes broadcast to peers, remote
 * writes flow back through ``observe``. When ``yDoc`` is null (collab
 * disabled, offline, or ``readOnly`` viewer), the hook falls back to a
 * plain in-memory ``Map<string, CellValue>`` so the editor still works
 * exactly as it did pre-collaboration.
 *
 * Multi-cell operations (paste, CSV import, bulk clear) wrap their
 * writes in ``yDoc.transact(...)`` so peers receive a single update
 * event instead of one per cell.
 */
export interface SpreadsheetCellsStore {
  cells: Map<string, CellValue>;
  setCell: (row: number, col: number, value: CellValue) => void;
  bulkUpdate: (mutator: (draft: Map<string, CellValue>) => void) => void;
  replaceAll: (next: Record<string, CellValue>) => void;
}

const Y_CELLS_KEY = "cells";

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

interface UseSpreadsheetCellsArgs {
  yDoc: Y.Doc | null;
  initialCells: Record<string, CellValue>;
}

export const useSpreadsheetCells = ({
  yDoc,
  initialCells,
}: UseSpreadsheetCellsArgs): SpreadsheetCellsStore => {
  // The Y.Map handle (when collaborating) or null (local-only).
  const yMap = useMemo<Y.Map<unknown> | null>(
    () => (yDoc ? (yDoc.getMap(Y_CELLS_KEY) as Y.Map<unknown>) : null),
    [yDoc]
  );

  // Local mirror of the cell map. When collaborating, this is rebuilt
  // from the Y.Map after every observed event; when not, it's the
  // canonical store.
  const [cells, setCells] = useState<Map<string, CellValue>>(() => {
    if (yMap && yMap.size > 0) return yMapToCellsMap(yMap);
    return new Map(Object.entries(initialCells));
  });

  // One-shot bootstrap into a fresh Y.Doc: when we first attach to a
  // Y.Map that's empty (no peers have written yet, no persisted yjs
  // snapshot), seed it with the JSON-snapshot cells so the local
  // editor and peers start from the same content.
  const bootstrappedRef = useRef(false);
  useEffect(() => {
    if (!yDoc || !yMap) return;
    if (bootstrappedRef.current) return;
    if (yMap.size > 0) {
      // Y.Map already has content (from yjs_state load or another
      // peer) — adopt it and skip the seed.
      setCells(yMapToCellsMap(yMap));
      bootstrappedRef.current = true;
      return;
    }
    const seed = Object.entries(initialCells);
    if (seed.length === 0) {
      bootstrappedRef.current = true;
      return;
    }
    yDoc.transact(() => {
      for (const [key, value] of seed) yMap.set(key, value);
    }, "spreadsheet-bootstrap");
    bootstrappedRef.current = true;
  }, [yDoc, yMap, initialCells]);

  // Subscribe to remote changes. ``transaction.local`` is true for
  // edits that originated in this client; we still rebuild the local
  // mirror because our ``setCells`` lives outside the Y.Map and needs
  // to reflect every committed change.
  useEffect(() => {
    if (!yMap) return;
    const handler = () => setCells(yMapToCellsMap(yMap));
    yMap.observe(handler);
    return () => yMap.unobserve(handler);
  }, [yMap]);

  const setCell = useCallback(
    (row: number, col: number, value: CellValue) => {
      const key = keyOf(row, col);
      if (yMap && yDoc) {
        yDoc.transact(() => {
          if (value === null || value === "") yMap.delete(key);
          else yMap.set(key, value);
        }, "spreadsheet-edit");
        // The observer will rebuild ``cells`` from the Y.Map; no need
        // to setCells here.
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
    (next: Record<string, CellValue>) => {
      if (yMap && yDoc) {
        yDoc.transact(() => {
          // Clear and re-populate inside one transaction.
          for (const key of Array.from(yMap.keys())) yMap.delete(key);
          for (const [key, value] of Object.entries(next)) yMap.set(key, value);
        }, "spreadsheet-replace-all");
        return;
      }
      setCells(new Map(Object.entries(next)));
    },
    [yDoc, yMap]
  );

  return { cells, setCell, bulkUpdate, replaceAll };
};

export const exportCellsToJsonObject = cellsMapToObject;
