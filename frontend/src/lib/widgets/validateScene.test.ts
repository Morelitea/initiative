import { describe, expect, it } from "vitest";

import { SCENE_LIMITS, WIDGET_API_VERSION } from "./sceneSpec";
import { SceneErrorCode, validateScene } from "./validateScene";

const wrap = (scene: unknown) => ({ v: WIDGET_API_VERSION, scene });

const expectCode = (raw: unknown, code: SceneErrorCode) => {
  const result = validateScene(raw);
  expect(result.ok).toBe(false);
  if (!result.ok) expect(result.code).toBe(code);
};

describe("validateScene — the trust boundary", () => {
  it("accepts each node kind the vocabulary declares", () => {
    const scenes: unknown[] = [
      { kind: "metric", value: 42, label: "Open tasks", format: "plain" },
      {
        kind: "series",
        mark: "bar",
        series: [{ name: "Done", points: [{ x: "Mon", y: 3 }], tone: "series-1" }],
      },
      {
        kind: "timeline",
        lanes: [{ label: "Alpha", spans: [{ start: 0, end: 10, progress: 0.5 }] }],
        scale: "week",
      },
      { kind: "funnel", stages: [{ label: "Leads", value: 100 }] },
      { kind: "progress", value: 3, min: 0, max: 10 },
      { kind: "matrix", cells: [{ x: 0, y: 0, value: 5 }], max: 10 },
      {
        kind: "table",
        columns: [{ key: "name", label: "Name" }],
        rows: [{ name: "Alpha" }],
      },
      { kind: "text", text: "hello", variant: "caption" },
      { kind: "empty", message: "No data" },
      {
        kind: "stack",
        direction: "column",
        children: [{ kind: "text", text: "a" }],
      },
    ];
    for (const scene of scenes) {
      const result = validateScene(wrap(scene));
      expect(result.ok, `${JSON.stringify(scene).slice(0, 60)} should validate`).toBe(true);
    }
  });

  it("rebuilds the scene instead of passing the input through", () => {
    const input = wrap({
      kind: "metric",
      value: 1,
      label: "ok",
      onClick: "alert(1)",
      dangerouslySetInnerHTML: { __html: "<img onerror=x>" },
      __proto__: { polluted: true },
    });
    const result = validateScene(input);
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    // Unknown keys are not copied, and the result is not the input object.
    expect(result.spec.scene).not.toBe((input as { scene: unknown }).scene);
    expect(Object.keys(result.spec.scene).sort()).toEqual(["kind", "label", "value"]);
    expect("onClick" in result.spec.scene).toBe(false);
    expect("dangerouslySetInnerHTML" in result.spec.scene).toBe(false);
  });

  it("does not let a table cell smuggle in a node", () => {
    const result = validateScene(
      wrap({
        kind: "table",
        columns: [{ key: "name" }],
        rows: [{ name: { kind: "stack", direction: "row", children: [] } }],
      })
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const table = result.spec.scene as { rows: Record<string, unknown>[] };
    expect(table.rows[0].name).toBeNull();
  });

  it("drops row keys the columns never declared", () => {
    const result = validateScene(
      wrap({
        kind: "table",
        columns: [{ key: "name" }],
        rows: [{ name: "Alpha", secret: "leaked" }],
      })
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const table = result.spec.scene as { rows: Record<string, unknown>[] };
    expect(Object.keys(table.rows[0])).toEqual(["name"]);
  });

  it("truncates over-long text rather than failing", () => {
    const long = "x".repeat(SCENE_LIMITS.maxTextLength + 500);
    const result = validateScene(wrap({ kind: "text", text: long }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect((result.spec.scene as { text: string }).text).toHaveLength(SCENE_LIMITS.maxTextLength);
  });

  it.each([
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["-Infinity", Number.NEGATIVE_INFINITY],
  ])("rejects %s, which would break every downstream scale", (_label, value) => {
    expectCode(wrap({ kind: "metric", value }), SceneErrorCode.VALUE_NOT_FINITE);
  });

  it("rejects a tone outside the theme palette", () => {
    expectCode(
      wrap({ kind: "text", text: "hi", tone: "url(javascript:alert(1))" }),
      SceneErrorCode.ENUM_INVALID
    );
  });

  it("rejects an unknown node kind", () => {
    expectCode(
      wrap({ kind: "iframe", src: "https://evil.test" }),
      SceneErrorCode.NODE_KIND_UNKNOWN
    );
  });

  it("rejects a widget written against a newer API than this build", () => {
    expectCode(
      { v: WIDGET_API_VERSION + 1, scene: { kind: "empty" } },
      SceneErrorCode.API_VERSION_UNSUPPORTED
    );
  });

  it("caps nesting depth", () => {
    let scene: unknown = { kind: "text", text: "deep" };
    for (let i = 0; i <= SCENE_LIMITS.maxDepth; i++) {
      scene = { kind: "stack", direction: "column", children: [scene] };
    }
    expectCode(wrap(scene), SceneErrorCode.TOO_DEEP);
  });

  it("caps total node count", () => {
    const children = Array.from({ length: SCENE_LIMITS.maxNodes + 1 }, () => ({
      kind: "text",
      text: "x",
    }));
    expectCode(
      wrap({ kind: "stack", direction: "column", children }),
      SceneErrorCode.TOO_MANY_NODES
    );
  });

  it("caps series points, so one widget cannot flood the render tree", () => {
    const points = Array.from({ length: SCENE_LIMITS.maxPoints + 1 }, (_, i) => ({
      x: i,
      y: i,
    }));
    expectCode(
      wrap({ kind: "series", mark: "line", series: [{ points }] }),
      SceneErrorCode.TOO_LARGE
    );
  });

  it("caps table rows", () => {
    const rows = Array.from({ length: SCENE_LIMITS.maxRows + 1 }, () => ({ name: "x" }));
    expectCode(wrap({ kind: "table", columns: [{ key: "name" }], rows }), SceneErrorCode.TOO_LARGE);
  });

  describe("timeline lanes nest", () => {
    it("keeps a lane tree, and the fields a Gantt row is made of", () => {
      const result = validateScene(
        wrap({
          kind: "timeline",
          now: 500,
          lanes: [
            {
              label: "Apollo",
              caption: "2/4",
              tone: "accent",
              collapsed: true,
              spans: [{ kind: "summary", start: 0, end: 100, progress: 0.5 }],
              children: [
                {
                  label: "Spec",
                  spans: [
                    {
                      kind: "bar",
                      start: 0,
                      end: 40,
                      caption: "Ada",
                      baseline: { start: 0, end: 30 },
                    },
                  ],
                },
                { label: "Sign-off", spans: [{ kind: "milestone", start: 90, end: 90 }] },
              ],
            },
          ],
        })
      );
      expect(result.ok).toBe(true);
      if (!result.ok) return;
      const scene = result.spec.scene as Extract<typeof result.spec.scene, { kind: "timeline" }>;
      expect(scene.now).toBe(500);
      expect(scene.lanes[0].collapsed).toBe(true);
      expect(scene.lanes[0].children).toHaveLength(2);
      expect(scene.lanes[0].children?.[0].spans[0].baseline).toEqual({ start: 0, end: 30 });
      expect(scene.lanes[0].children?.[1].spans[0].kind).toBe("milestone");
    });

    it("rejects a span shape the renderer has no mark for", () => {
      expectCode(
        wrap({ kind: "timeline", lanes: [{ spans: [{ kind: "spiral", start: 0, end: 1 }] }] }),
        SceneErrorCode.ENUM_INVALID
      );
    });

    it("counts lanes across the whole tree, not per level", () => {
      // A chain, not a list: each level holds one lane, so no single array is
      // near the cap while the total is well past it.
      let deep: unknown = { spans: [] };
      for (let index = 0; index < SCENE_LIMITS.maxLanes; index++) {
        deep = { spans: [], children: [deep] };
      }
      const result = validateScene(wrap({ kind: "timeline", lanes: [deep] }));
      expect(result.ok).toBe(false);
    });

    it("caps how deeply lanes nest", () => {
      let deep: unknown = { spans: [] };
      for (let index = 0; index <= SCENE_LIMITS.maxLaneDepth; index++) {
        deep = { spans: [], children: [deep] };
      }
      expectCode(wrap({ kind: "timeline", lanes: [deep] }), SceneErrorCode.TOO_DEEP);
    });

    it("drops a key a lane never declared", () => {
      const result = validateScene(
        wrap({
          kind: "timeline",
          lanes: [{ spans: [{ start: 0, end: 1, onClick: "alert(1)" }], href: "javascript:0" }],
        })
      );
      expect(result.ok).toBe(true);
      if (!result.ok) return;
      const scene = result.spec.scene as Extract<typeof result.spec.scene, { kind: "timeline" }>;
      expect(scene.lanes[0]).not.toHaveProperty("href");
      expect(scene.lanes[0].spans[0]).not.toHaveProperty("onClick");
    });
  });

  it("never throws, whatever it is handed", () => {
    const hostile: unknown[] = [
      undefined,
      null,
      42,
      "scene",
      [],
      { v: 1 },
      { v: 1, scene: null },
      { v: 1, scene: { kind: "stack", direction: "row", children: "not-an-array" } },
      { v: "one", scene: { kind: "empty" } },
    ];
    for (const input of hostile) {
      expect(() => validateScene(input)).not.toThrow();
      expect(validateScene(input).ok).toBe(false);
    }
  });
});
