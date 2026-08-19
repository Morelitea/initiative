import { describe, expect, it } from "vitest";

import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { type SceneTableT, sceneToTables } from "@/lib/widgets/sceneTable";

const t = ((key: string) => key) as unknown as SceneTableT;

describe("sceneToTables", () => {
  it("returns a table scene unchanged", () => {
    const node: SceneNode = {
      kind: "table",
      columns: [{ key: "a" }],
      rows: [{ a: 1 }],
    };
    expect(sceneToTables(node, t)).toEqual([node]);
  });

  it("turns a metric into its label and value", () => {
    const [table] = sceneToTables(
      { kind: "metric", value: 42, label: "Open tasks", format: "plain" },
      t
    );
    expect(table.rows).toEqual([{ label: "Open tasks", value: 42 }]);
  });

  it("merges series on x, one column each, the way the chart does", () => {
    const [table] = sceneToTables(
      {
        kind: "series",
        mark: "bar",
        series: [
          { name: "Done", points: [{ x: "Apollo", y: 3 }] },
          {
            name: "Remaining",
            points: [
              { x: "Apollo", y: 5 },
              { x: "Zeus", y: 2 },
            ],
          },
        ],
      },
      t
    );
    expect(table.columns.map((column) => column.key)).toEqual(["x", "s0", "s1"]);
    expect(table.rows).toEqual([
      { x: "Apollo", s0: 3, s1: 5 },
      { x: "Zeus", s1: 2 },
    ]);
  });

  it("flattens nested timeline lanes, carrying the nesting into the label", () => {
    const [table] = sceneToTables(
      {
        kind: "timeline",
        lanes: [
          {
            label: "Apollo",
            spans: [{ start: 1, end: 2, progress: 0.5 }],
            children: [{ label: "Draft the spec", spans: [{ start: 1, end: 2 }] }],
          },
        ],
      },
      t
    );
    expect(table.rows).toHaveLength(2);
    expect(table.rows[0].lane).toBe("Apollo");
    expect(table.rows[1].lane).toBe("— Draft the spec");
  });

  it("gives a lane with no spans null dates rather than inventing them", () => {
    const [table] = sceneToTables({ kind: "timeline", lanes: [{ label: "Empty", spans: [] }] }, t);
    expect(table.rows[0]).toMatchObject({ start: null, end: null });
  });

  it("reads matrix cells through their own axis labels where a scene gave them", () => {
    const [table] = sceneToTables(
      {
        kind: "matrix",
        cells: [{ x: 0, y: 1, value: 4 }],
        xLabels: ["Aug"],
        yLabels: ["Sun", "Mon"],
      },
      t
    );
    expect(table.rows[0]).toMatchObject({ x: "Aug", y: "Mon", value: 4 });
  });

  it("gives a stack one table per child rather than merging them", () => {
    // The children are separate pictures; interleaving their rows would invent
    // a relationship the scene never claimed.
    const tables = sceneToTables(
      {
        kind: "stack",
        direction: "column",
        children: [
          { kind: "metric", value: 1 },
          {
            kind: "series",
            mark: "line",
            series: [{ points: [{ x: 1, y: 2 }] }],
          },
        ],
      },
      t
    );
    expect(tables).toHaveLength(2);
  });

  it("returns nothing for a scene with nothing to tabulate", () => {
    expect(sceneToTables({ kind: "empty", message: "No tasks match" }, t)).toEqual([]);
  });

  it("keeps a funnel's stage order", () => {
    const [table] = sceneToTables(
      {
        kind: "funnel",
        stages: [
          { label: "Opened", value: 10 },
          { label: "Started", value: 6 },
        ],
      },
      t
    );
    expect(table.rows.map((row) => row.stage)).toEqual(["Opened", "Started"]);
  });
});
