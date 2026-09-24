import { describe, expect, it } from "vitest";

import exports from "../../../public/locales/en/exports.json";
import {
  DOCUMENT_TYPE_FORMATS,
  documentSelectionFormats,
  REPORT_DOCUMENT_FORMATS,
  REPORT_TOOL_FORMATS,
  TOOL_EXPORT_FORMATS,
} from "./formats";

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

describe("format labels", () => {
  // Every export surface translates these keys in the ``exports`` namespace.
  // A key that resolves nowhere renders as the raw ``export.formatPdf``, which
  // is what the community export wizard showed while it looked them up under
  // ``tasks`` after they had moved.
  const lists = [
    ...Object.values(DOCUMENT_TYPE_FORMATS),
    ...Object.values(TOOL_EXPORT_FORMATS),
    ...Object.values(REPORT_TOOL_FORMATS),
    ...Object.values(REPORT_DOCUMENT_FORMATS),
  ];
  const labelKeys = [...new Set(lists.flatMap((list) => (list ?? []).map((o) => o.labelKey)))];

  it.each(labelKeys)("%s has English wording in exports.json", (labelKey) => {
    const value = labelKey
      .split(".")
      .reduce<unknown>(
        (node, part) => (node as Record<string, unknown> | undefined)?.[part],
        exports
      );
    expect(typeof value).toBe("string");
  });
});
