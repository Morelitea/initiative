/**
 * How a binding becomes a request.
 *
 * The load-bearing case is scope. A dashboard reads the initiative it lives on,
 * and without one nothing is fetched at all — a widget on no initiative must
 * fail closed rather than fan out guild-wide. That difference is invisible on a
 * canvas (a chart with plausible-looking numbers), so it is pinned here on the
 * request itself rather than on what gets drawn.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";

const idle = { data: undefined, isLoading: false, isError: false };
const useSqlQuery = vi.fn(() => idle);
const useDocument = vi.fn(() => idle);

vi.mock("@/hooks/useSqlQuery", () => ({
  useSqlQuery: (...args: unknown[]) => useSqlQuery(...args),
}));
vi.mock("@/hooks/useDocuments", () => ({
  useDocument: (...args: unknown[]) => useDocument(...args),
}));
// Mocked like every other sibling: this file is about how a binding becomes a
// request, and the app hooks reach for guild context a bare renderHook has no
// provider for.
vi.mock("@/hooks/useAppData", () => ({
  useAppData: () => idle,
  useAppWidgetCatalog: () => idle,
}));

/** The statement the query hook was actually asked for. */
const asked = (): unknown => useSqlQuery.mock.calls.at(-1)?.[0];
/** The initiative it was asked to narrow the answer to. */
const scopedTo = (): unknown => useSqlQuery.mock.calls.at(-1)?.[1];
const enabled = (): boolean =>
  Boolean((useSqlQuery.mock.calls.at(-1)?.[2] as { enabled?: boolean } | undefined)?.enabled);

const run = (binding: WidgetBinding, initiativeId: number | undefined) =>
  renderHook(() => useWidgetData(binding, initiativeId));

beforeEach(() => {
  useSqlQuery.mockClear();
  useDocument.mockClear();
});

describe("a query binding", () => {
  it("asks for the statement it was given", () => {
    run({ source: "query", sql: "SELECT title FROM tasks" }, 4);
    expect(asked()).toBe("SELECT title FROM tasks");
    expect(enabled()).toBe(true);
  });

  it("asks about the dashboard's own initiative", () => {
    // A statement names datasets, not a scope, so the dashboard's own
    // initiative is what decides which rows the answer is about.
    run({ source: "query", sql: "SELECT title FROM tasks" }, 4);
    expect(scopedTo()).toBe(4);
  });

  it("asks for nothing without an initiative", () => {
    // Fail closed: a widget with no initiative behind it is unbound, not
    // guild-wide.
    run({ source: "query", sql: "SELECT title FROM tasks" }, undefined);
    expect(enabled()).toBe(false);
  });

  it("asks for nothing when the binding has no statement yet", () => {
    const { result } = run({ source: "query" }, 4);
    expect(asked()).toBeNull();
    expect(result.current.isUnbound).toBe(true);
  });

  it("reads a refused statement as the author's problem, not the viewer's", () => {
    // A name the registry does not have is the author's to fix; it is not an
    // access outcome, so it must not render as one.
    useSqlQuery.mockReturnValue({ ...idle, isError: true });
    const { result } = run({ source: "query", sql: "SELECT nope FROM tasks" }, 4);
    expect(result.current.isRestricted).toBe(false);
    expect(result.current.errorCode).toBeDefined();
    useSqlQuery.mockReturnValue(idle);
  });

  it("reports what came back as columns and rows", () => {
    useSqlQuery.mockReturnValue({
      ...idle,
      data: {
        columns: [
          { name: "title", type: "text" },
          { name: "n", type: "number" },
        ],
        rows: [["Ship it", 3]],
        truncated: true,
      },
    });
    const { result } = run({ source: "query", sql: "SELECT title, count(*) FROM tasks" }, 4);
    expect(result.current.data).toMatchObject({
      source: "rows",
      columns: [
        { name: "title", type: "text" },
        { name: "n", type: "number" },
      ],
      rows: [["Ship it", 3]],
    });
    expect(result.current.meta?.truncated).toBe(true);
    useSqlQuery.mockReturnValue(idle);
  });
});

describe("a sheet-range binding", () => {
  it("asks for nothing until it has both a document and a range", () => {
    const { result } = run({ source: "sheet_range", document_id: 3 }, 4);
    expect(result.current.isUnbound).toBe(true);
  });

  it("treats a document in another initiative as absent, not readable", () => {
    // Bindings do not reach across initiatives; an id pointing elsewhere
    // resolves the same way a deleted or unshared one does.
    useDocument.mockReturnValue({ ...idle, data: { initiative_id: 99, content: null } });
    const { result } = run({ source: "sheet_range", document_id: 3, range: "A1:B2" }, 4);
    expect(result.current.isRestricted).toBe(true);
    useDocument.mockReturnValue(idle);
  });
});
