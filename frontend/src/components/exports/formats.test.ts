import { describe, expect, it } from "vitest";

import { documentSelectionFormats } from "./formats";

describe("documentSelectionFormats", () => {
  it("keeps the type's own labels for a single-type selection", () => {
    const formats = documentSelectionFormats(["native", "native"]);
    expect(formats.map((f) => f.format)).toEqual(["pdf", "md", "docx", "json"]);
    expect(formats.find((f) => f.format === "json")?.labelKey).toBe("export.formatJson");
  });

  it("intersects formats across a mixed selection with generic labels", () => {
    const formats = documentSelectionFormats(["native", "spreadsheet"]);
    expect(formats.map((f) => f.format)).toEqual(["json"]);
    // Mixed selection: the generic label, since entries differ per type.
    expect(formats[0].labelKey).toBe("export.formatJson");
  });

  it("returns empty when the types share no format", () => {
    expect(documentSelectionFormats(["native", "file"])).toEqual([]);
    expect(documentSelectionFormats([])).toEqual([]);
  });

  it("whiteboards and spreadsheets share the json envelope", () => {
    expect(documentSelectionFormats(["whiteboard", "spreadsheet"]).map((f) => f.format)).toEqual([
      "json",
    ]);
  });
});

describe("smart link formats", () => {
  it("smart links offer markdown and the importable json envelope", () => {
    const formats = documentSelectionFormats(["smart_link"]);
    expect(formats.map((f) => f.format)).toEqual(["md", "json"]);
  });

  it("smart links now intersect with text documents on md and json", () => {
    expect(documentSelectionFormats(["native", "smart_link"]).map((f) => f.format)).toEqual([
      "md",
      "json",
    ]);
  });
});
