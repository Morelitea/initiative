/**
 * The picker previews a widget by running it over these rows, so a source with
 * no sample is a source that previews blank — which reads as "this widget shows
 * nothing" rather than "we forgot the sample". `sampleFor` is deliberately total
 * so that gap can't crash the dialog; this is what keeps it from going unnoticed.
 *
 * Derived from the generated `BindingSource` enum, which comes from the
 * backend's `ALL_SOURCES` — so adding a source server-side fails here until the
 * sample lands, rather than at the first person to open the picker.
 */
import { describe, expect, it } from "vitest";

import { BindingSource } from "@/api/generated/initiativeAPI.schemas";

import { ALL_SAMPLES, sampleFor } from "./sampleData";

describe("widget sample data", () => {
  it("covers exactly the binding sources the backend declares", () => {
    expect(ALL_SAMPLES.map((sample) => sample.source).sort()).toEqual(
      Object.values(BindingSource).sort()
    );
  });

  it("gives every source something to draw", () => {
    for (const source of Object.values(BindingSource)) {
      expect(sampleFor(source), source).toBeDefined();
    }
  });
});
