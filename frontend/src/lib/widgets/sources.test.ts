import { describe, expect, it } from "vitest";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import { entityParams, paramsFor, SOURCES, unboundSlots } from "@/lib/widgets/sources";

const binding = (partial: Partial<WidgetBinding> & { source: WidgetSource }): WidgetBinding =>
  partial as WidgetBinding;

describe("the source registry", () => {
  it("describes the three bindings there are", () => {
    // The registry is what the config dialog, the provenance line and
    // unboundSlots all read, so a binding missing here has no controls and no
    // description anywhere.
    expect(Object.keys(SOURCES).sort()).toEqual(["app", "query", "sheet_range"]);
  });

  it("says a statement is the whole of a query binding", () => {
    const params = paramsFor("query");
    expect(params).toHaveLength(1);
    expect(params[0]).toMatchObject({ kind: "sql", key: "sql", required: true });
  });

  it("reports the parameters a binding still needs", () => {
    expect(unboundSlots(binding({ source: "query" }))).toEqual(["sql"]);
    expect(unboundSlots(binding({ source: "query", sql: "SELECT 1" }))).toEqual([]);
    expect(unboundSlots(binding({ source: "sheet_range" })).sort()).toEqual([
      "document_id",
      "range",
    ]);
    expect(
      unboundSlots(binding({ source: "sheet_range", document_id: 3, range: "A1:B2" }))
    ).toEqual([]);
  });

  it("names no entity for a statement, and one for a sheet range", () => {
    expect(entityParams("query")).toEqual([]);
    expect(entityParams("sheet_range").map((param) => param.entity)).toEqual(["document"]);
  });

  it("says nothing about a source it does not know", () => {
    expect(unboundSlots(binding({ source: "nonsense" as WidgetSource }))).toEqual([]);
    expect(paramsFor("nonsense")).toEqual([]);
  });
});
