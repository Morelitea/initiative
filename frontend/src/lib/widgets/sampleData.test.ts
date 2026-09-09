/**
 * The picker previews a widget by running it over these rows, so a widget with
 * no sample previews blank — which reads as "this widget shows nothing" rather
 * than "we forgot the sample". `sampleFor` is deliberately total so that gap
 * cannot crash the dialog; this is what keeps it from going unnoticed.
 *
 * Derived from the built-in registry, so a new widget fails here until its
 * sample lands rather than at the first person to open the picker.
 */
import { describe, expect, it } from "vitest";

import { BUILTIN_WIDGET_TYPES } from "./registry";
import { emptySample, sampleFor } from "./sampleData";

describe("widget sample data", () => {
  it("gives every built-in widget something to draw", () => {
    for (const type of BUILTIN_WIDGET_TYPES) {
      const sample = sampleFor(type);
      expect(sample.source, type).toBe("rows");
      expect(sample.columns.length, type).toBeGreaterThan(0);
      expect(sample.rows.length, type).toBeGreaterThan(0);
    }
  });

  it("describes every column it hands over", () => {
    for (const type of BUILTIN_WIDGET_TYPES) {
      const sample = sampleFor(type);
      for (const row of sample.rows) {
        expect(row.length, type).toBe(sample.columns.length);
      }
    }
  });

  it("has an empty counterpart with the same columns", () => {
    for (const type of BUILTIN_WIDGET_TYPES) {
      const empty = emptySample(type);
      expect(empty.rows).toEqual([]);
      expect(empty.columns).toEqual(sampleFor(type).columns);
    }
  });
});
