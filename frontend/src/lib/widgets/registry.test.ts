/**
 * Built-in widget drift + conformance.
 *
 * Two things are checked here, and the second is the point of the whole
 * one-harness design: the built-ins are not merely *described* as sandboxed
 * modules, they are executed as ones — through the same runtime, validator, and
 * vocabulary an installed listing's widget would go through. A built-in that
 * quietly needed a capability, or emitted something outside the SceneSpec,
 * fails here rather than at a customer's dashboard.
 */
import { describe, expect, it } from "vitest";

import { WidgetType } from "@/api/generated/initiativeAPI.schemas";

import { BUILTIN_WIDGET_TYPES, builtinWidgetSource } from "./registry";
import { renderInSandbox } from "./runtime/sandbox";
import { ALL_SAMPLES, SOURCES_BY_WIDGET, sampleFor } from "./sampleData";
import { validateScene } from "./validateScene";

describe("built-in widget registry", () => {
  it("covers exactly the widget types the backend declares", () => {
    expect(BUILTIN_WIDGET_TYPES.sort()).toEqual(Object.values(WidgetType).sort());
  });

  it("has no renderer for a type the backend does not know", () => {
    expect(builtinWidgetSource("iframe")).toBeUndefined();
  });
});

describe("built-ins run in the sandbox like any other widget", () => {
  const cases = Object.entries(SOURCES_BY_WIDGET).flatMap(([type, sources]) =>
    sources.map((source) => ({ type, source }))
  );

  it.each(cases)("$type draws $source", async ({ type, source }) => {
    const widgetSource = builtinWidgetSource(type);
    expect(widgetSource, `no module for ${type}`).toBeDefined();

    const result = await renderInSandbox({
      source: widgetSource as string,
      data: sampleFor(source, type),
      config: {},
      now: Date.UTC(2026, 7, 11),
    });

    expect(result.ok, `${type}/${source} failed: ${JSON.stringify(result)}`).toBe(true);
    if (!result.ok) return;

    const validation = validateScene(result.value);
    expect(
      validation.ok,
      `${type}/${source} emitted an invalid scene: ${JSON.stringify(validation)}`
    ).toBe(true);
    if (!validation.ok) return;

    // A widget handed data it can draw should draw it, not bail to an empty
    // tile — that would hide a broken binding behind a plausible-looking card.
    expect(validation.spec.scene.kind, `${type}/${source} fell through to an empty tile`).not.toBe(
      "empty"
    );
  });

  it.each(BUILTIN_WIDGET_TYPES)(
    "%s degrades to an empty tile for a source it cannot draw",
    async (type) => {
      const drawable = new Set(SOURCES_BY_WIDGET[type]);
      const foreign = ALL_SAMPLES.find((f) => !drawable.has(f.source));
      expect(foreign, `${type} draws every source`).toBeDefined();

      const result = await renderInSandbox({
        source: builtinWidgetSource(type) as string,
        data: foreign?.data,
        config: {},
      });
      expect(result.ok).toBe(true);
      if (!result.ok) return;
      const validation = validateScene(result.value);
      expect(validation.ok).toBe(true);
      if (!validation.ok) return;
      expect(validation.spec.scene.kind).toBe("empty");
    }
  );

  it.each(BUILTIN_WIDGET_TYPES)("%s survives empty data", async (type) => {
    for (const sample of ALL_SAMPLES) {
      const result = await renderInSandbox({
        source: builtinWidgetSource(type) as string,
        data: sample.empty,
        config: {},
      });
      expect(result.ok, `${type} threw on empty ${sample.source}: ${JSON.stringify(result)}`).toBe(
        true
      );
      if (!result.ok) continue;
      expect(validateScene(result.value).ok).toBe(true);
    }
  });
});
