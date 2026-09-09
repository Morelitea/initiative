/**
 * What a tile may say about where its data came from.
 *
 * The assertions that matter are about *absence*: an id this viewer cannot
 * resolve is reported as unresolvable and never named, and nothing is called
 * unresolvable while a lookup is still in flight.
 */
import { describe, expect, it } from "vitest";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import {
  bindingScope,
  EMPTY_LABELS,
  type EntityLabels,
  queryScope,
} from "@/lib/widgets/provenance";

const binding = (partial: Partial<WidgetBinding> & { source: WidgetSource }): WidgetBinding =>
  partial as WidgetBinding;

const labels = (documents: [number, string][], ready = true): EntityLabels => ({
  document: new Map(documents),
  ready,
});

describe("binding scope", () => {
  it("names a document the viewer can resolve", () => {
    const chips = bindingScope(
      binding({ source: "sheet_range", document_id: 7, range: "A1:B2" }),
      labels([[7, "Q3 figures"]])
    );
    expect(chips).toEqual([{ key: "document_id", label: "Q3 figures", restricted: false }]);
  });

  it("reports an unresolvable id without naming it", () => {
    const chips = bindingScope(
      binding({ source: "sheet_range", document_id: 7, range: "A1:B2" }),
      labels([])
    );
    expect(chips).toEqual([{ key: "document_id", label: undefined, restricted: true }]);
  });

  it("calls nothing unresolvable while the lookup is in flight", () => {
    const chips = bindingScope(
      binding({ source: "sheet_range", document_id: 7, range: "A1:B2" }),
      EMPTY_LABELS
    );
    expect(chips).toEqual([{ key: "document_id", label: undefined, restricted: false }]);
  });

  it("says nothing about a parameter with no value", () => {
    expect(bindingScope(binding({ source: "sheet_range" }), labels([]))).toEqual([]);
  });

  it("says nothing about a statement, which names no ids", () => {
    expect(
      bindingScope(binding({ source: "query", sql: "SELECT title FROM tasks" }), labels([]))
    ).toEqual([]);
  });
});

describe("query scope", () => {
  it("reports the datasets the server said were read", () => {
    expect(queryScope(["projects", "tasks"])).toEqual([
      { key: "projects", label: "projects", restricted: false },
      { key: "tasks", label: "tasks", restricted: false },
    ]);
  });

  it("reports nothing for a statement that read nothing", () => {
    expect(queryScope([])).toEqual([]);
  });
});
