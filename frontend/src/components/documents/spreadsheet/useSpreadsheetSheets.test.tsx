import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { useSpreadsheetSheets } from "@/components/documents/spreadsheet/useSpreadsheetSheets";
import {
  SHEET_CELLS,
  sheetContainer,
  sheetPart,
  sheetsRoot,
} from "@/components/documents/spreadsheet/workbookDoc";
import { parseSpreadsheetContent } from "@/lib/spreadsheet/content";

const content = (cells: Record<string, unknown>) =>
  parseSpreadsheetContent({ cells: cells as Record<string, string | number> });

const cellsOf = (doc: Y.Doc, id: string): Record<string, unknown> =>
  (sheetPart(sheetContainer(doc, id), SHEET_CELLS)?.toJSON() ?? {}) as Record<string, unknown>;

/** Apply one doc's full state to another, the way the provider applies the
 *  server's initial sync. */
const applyState = (target: Y.Doc, source: Y.Doc) =>
  Y.applyUpdate(target, Y.encodeStateAsUpdate(source));

describe("useSpreadsheetSheets — seeding gate", () => {
  it("seeds immediately by default (local / non-collaborative doc)", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({ yDoc: doc, initialContent: content({ "0:0": "hello" }) })
    );
    expect(result.current.sheets).toHaveLength(1);
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "hello" });
  });

  it("does not seed while seedAllowed is false", () => {
    const doc = new Y.Doc();
    const { result } = renderHook(() =>
      useSpreadsheetSheets({
        yDoc: doc,
        initialContent: content({ "0:0": "stale" }),
        seedAllowed: false,
      })
    );
    expect(sheetsRoot(doc).size).toBe(0);
    expect(result.current.sheets).toHaveLength(0);
  });

  it("seeds a still-empty doc once seedAllowed flips true (first-ever collab session)", () => {
    const doc = new Y.Doc();
    const { result, rerender } = renderHook(
      ({ seedAllowed }: { seedAllowed: boolean }) =>
        useSpreadsheetSheets({
          yDoc: doc,
          initialContent: content({ "0:0": "bootstrap" }),
          seedAllowed,
        }),
      { initialProps: { seedAllowed: false } }
    );
    expect(sheetsRoot(doc).size).toBe(0);

    rerender({ seedAllowed: true });
    expect(result.current.sheets).toHaveLength(1);
    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "bootstrap" });
  });

  it("leaves synced remote state untouched when seedAllowed flips true (rejoin)", () => {
    // The rejoin scenario the gate exists for: another user's edits arrive
    // via the initial sync while our REST snapshot is stale. Seeding before
    // (or after) that sync must not push the stale snapshot into the doc.
    const server = new Y.Doc();
    renderHook(() =>
      useSpreadsheetSheets({ yDoc: server, initialContent: content({ "0:0": "edited-by-A" }) })
    );

    const doc = new Y.Doc();
    const { result, rerender } = renderHook(
      ({ seedAllowed }: { seedAllowed: boolean }) =>
        useSpreadsheetSheets({
          yDoc: doc,
          initialContent: content({ "0:0": "stale-snapshot" }),
          seedAllowed,
        }),
      { initialProps: { seedAllowed: false } }
    );
    expect(sheetsRoot(doc).size).toBe(0);

    // Initial sync lands, then the provider reports synced.
    act(() => applyState(doc, server));
    rerender({ seedAllowed: true });

    expect(cellsOf(doc, "s1")).toEqual({ "0:0": "edited-by-A" });
    expect(result.current.cellsBySheet.get("s1")?.get("0:0")).toBe("edited-by-A");
    // And nothing was broadcast back that the server doesn't already have.
    expect(Y.encodeStateAsUpdate(doc, Y.encodeStateVector(server)).length).toBeLessThanOrEqual(2);
  });
});
