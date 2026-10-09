/**
 * Built-in widget drift + conformance.
 *
 * Two things are checked here: the registry matches the backend's widget types,
 * and each built-in's code works out a model its template's elements accept,
 * held to the same validator and limits a plug-in's output is. A built-in that
 * drew something outside the vocabulary fails here rather than at a customer's
 * dashboard.
 */
import { describe, expect, it } from "vitest";

import { WidgetType } from "@/api/generated/initiativeAPI.schemas";

import type { BuiltinWidget } from "./builtins/builtin";
import type { TabularData } from "./dataShapes";
import { BUILTIN_WIDGET_TYPES, builtinWidget } from "./registry";
import { emptySample, sampleFor } from "./sampleData";
import { resolveMapping } from "./shape";
import { validateScene } from "./validateScene";

/** A built-in's model, checked as the elements check it. */
const draw = (type: string, data: TabularData, slots: Record<string, number[]>, now?: number) =>
  validateScene({
    v: 1,
    scene: (builtinWidget(type) as BuiltinWidget).shape(data, {}, { slots, now }),
  });

describe("built-in widget registry", () => {
  it("covers exactly the widget types the backend declares", () => {
    expect(BUILTIN_WIDGET_TYPES.sort()).toEqual(Object.values(WidgetType).sort());
  });

  it("has no renderer for a type the backend does not know", () => {
    expect(builtinWidget("iframe")).toBeUndefined();
  });
});

describe("each built-in's code draws what its elements accept", () => {
  /** The shape each widget declares, mirrored from the backend's WIDGET_SPECS.
   *  The served catalog is the authority; this copy is what lets the widget
   *  tests run without a backend, and `dashboards_test.py` is what would catch
   *  the two drifting. */
  const SHAPES: Record<
    string,
    { name: string; types: string[]; required?: boolean; repeatable?: boolean }[]
  > = {
    gantt: [
      { name: "label", types: ["text", "enum", "reference"] },
      { name: "start", types: ["date"] },
      { name: "end", types: ["date"] },
      { name: "group", types: ["text", "enum", "reference"], required: false },
    ],
    stat: [
      { name: "value", types: ["number"] },
      { name: "label", types: ["text", "enum", "reference"], required: false },
    ],
    chart: [
      { name: "label", types: ["text", "enum", "reference", "date"] },
      { name: "value", types: ["number"], repeatable: true },
    ],
    funnel: [
      { name: "label", types: ["text", "enum", "reference"] },
      { name: "value", types: ["number"] },
    ],
    progress: [
      { name: "value", types: ["number"] },
      { name: "total", types: ["number"], required: false },
      { name: "label", types: ["text", "enum", "reference"], required: false },
    ],
    heatmap: [
      { name: "at", types: ["date"] },
      { name: "value", types: ["number"] },
    ],
    board: [
      { name: "card", types: ["text", "enum", "reference"] },
      { name: "column", types: ["text", "enum", "reference"] },
      { name: "date", types: ["date"], required: false },
    ],
    table: [],
  };

  const slotsFor = (type: string, data: { columns: { name: string; type: string }[] }) =>
    resolveMapping(
      data.columns as never,
      (SHAPES[type] ?? []).map((slot) => ({
        required: true,
        repeatable: false,
        ...slot,
      })) as never
    );

  it.each(BUILTIN_WIDGET_TYPES)("%s draws the shape it declares", async (type) => {
    const data = sampleFor(type);
    const validation = draw(type, data, slotsFor(type, data), Date.UTC(2026, 7, 11));
    expect(validation.ok, `${type} drew something invalid: ${JSON.stringify(validation)}`).toBe(
      true
    );
    if (!validation.ok) return;
    // A widget handed data it can draw should draw it, not bail to an empty
    // tile — that would hide a broken binding behind a plausible-looking card.
    expect(validation.spec.scene.kind, `${type} fell through to an empty tile`).not.toBe("empty");
  });

  it.each(BUILTIN_WIDGET_TYPES)(
    "%s degrades to an empty tile with nothing mapped",
    async (type) => {
      // Every widget but the table needs its slots filled; the table draws
      // whatever it is given, which is what makes it the fallback.
      const validation = draw(type, sampleFor(type), {});
      expect(validation.ok).toBe(true);
      if (!validation.ok) return;
      expect(validation.spec.scene.kind).toBe(type === "table" ? "table" : "empty");
    }
  );

  it.each(BUILTIN_WIDGET_TYPES)("%s survives empty data", async (type) => {
    const data = emptySample(type);
    const validation = draw(type, data, slotsFor(type, data));
    expect(validation.ok, `${type} threw on empty rows: ${JSON.stringify(validation)}`).toBe(true);
  });
});
