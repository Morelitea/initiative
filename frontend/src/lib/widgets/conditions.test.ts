import { describe, expect, it } from "vitest";

import {
  countLeaves,
  expandConditions,
  fieldSpec,
  isGroup,
  readConditions,
  TASK_FILTER_FIELDS,
} from "@/lib/widgets/conditions";

const DAY = 86_400_000;
const NOW = Date.UTC(2026, 7, 3);

describe("readConditions", () => {
  it("reads a flat list of comparisons", () => {
    const nodes = readConditions([
      { field: "priority", op: "in_", value: ["high", "urgent"] },
      { field: "due_date", op: "lt", value: "2026-09-30T00:00:00Z" },
    ]);
    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toEqual({ field: "priority", op: "in_", value: ["high", "urgent"] });
  });

  it("accepts the single-group form a definition may carry", () => {
    const nodes = readConditions({
      logic: "or",
      conditions: [{ field: "priority", op: "in_", value: ["high"] }],
    });
    expect(nodes).toHaveLength(1);
    expect(isGroup(nodes[0])).toBe(true);
  });

  it("drops a leaf with no field or an operator the endpoint does not have", () => {
    expect(readConditions([{ op: "eq", value: 1 }])).toEqual([]);
    expect(readConditions([{ field: "priority", op: "regex", value: "x" }])).toEqual([]);
  });

  it("keeps a negation flag only when it is actually set", () => {
    const [negated] = readConditions([{ field: "priority", op: "eq", value: "low", negate: true }]);
    expect(negated).toHaveProperty("negate", true);
    const [plain] = readConditions([{ field: "priority", op: "eq", value: "low", negate: false }]);
    expect(plain).not.toHaveProperty("negate");
  });

  it("drops a group nested deeper than the round trip allows", () => {
    // The endpoint's parser caps group depth, and the host already spends a
    // level scoping the dashboard's initiative — so a second nested group is
    // dropped here rather than sent and rejected as a whole.
    const nodes = readConditions([
      {
        logic: "or",
        conditions: [
          { field: "priority", op: "in_", value: ["high"] },
          { logic: "and", conditions: [{ field: "title", op: "ilike", value: "x" }] },
        ],
      },
    ]);
    expect(nodes).toHaveLength(1);
    const group = nodes[0];
    expect(isGroup(group) && group.conditions).toHaveLength(1);
  });

  it("drops a group that ends up with nothing readable in it", () => {
    expect(readConditions([{ logic: "or", conditions: [{ nonsense: true }] }])).toEqual([]);
  });

  it("keeps only scalar entries inside a list value", () => {
    const [leaf] = readConditions([
      { field: "tag_ids", op: "in_", value: [1, "two", { three: 3 }, null] },
    ]);
    expect(leaf).toEqual({ field: "tag_ids", op: "in_", value: [1, "two"] });
  });
});

describe("countLeaves", () => {
  it("counts comparisons through groups, not top-level entries", () => {
    const nodes = readConditions([
      { field: "priority", op: "in_", value: ["high"] },
      {
        logic: "or",
        conditions: [
          { field: "title", op: "ilike", value: "a" },
          { field: "title", op: "ilike", value: "b" },
        ],
      },
    ]);
    expect(countLeaves(nodes)).toBe(3);
  });
});

describe("expandConditions", () => {
  it("resolves a relative date against the given instant", () => {
    const nodes = readConditions([{ field: "due_date", op: "lt", value: { relative: 30 } }]);
    const [leaf] = expandConditions(nodes, NOW);
    expect(leaf).toEqual({
      field: "due_date",
      op: "lt",
      value: new Date(NOW + 30 * DAY).toISOString(),
    });
  });

  it("resolves negative offsets as the past", () => {
    const nodes = readConditions([{ field: "created_at", op: "gte", value: { relative: -7 } }]);
    const [leaf] = expandConditions(nodes, NOW);
    expect(leaf).toHaveProperty("value", new Date(NOW - 7 * DAY).toISOString());
  });

  it("leaves an absolute date alone", () => {
    const nodes = readConditions([{ field: "due_date", op: "lt", value: "2026-09-30T00:00:00Z" }]);
    expect(expandConditions(nodes, NOW)).toEqual(nodes);
  });

  it("reaches relative dates inside a group", () => {
    const nodes = readConditions([
      { logic: "or", conditions: [{ field: "due_date", op: "lt", value: { relative: 1 } }] },
    ]);
    const [group] = expandConditions(nodes, NOW);
    expect(isGroup(group) && group.conditions[0]).toHaveProperty(
      "value",
      new Date(NOW + DAY).toISOString()
    );
  });

  it("moves with the clock, so a saved question does not freeze on its save date", () => {
    const nodes = readConditions([{ field: "due_date", op: "lt", value: { relative: 30 } }]);
    const [first] = expandConditions(nodes, NOW);
    const [later] = expandConditions(nodes, NOW + 10 * DAY);
    expect(first).not.toEqual(later);
  });
});

describe("the field catalog", () => {
  it("does not offer the initiative as a filter", () => {
    // A dashboard reads its own initiative; a binding cannot say otherwise.
    expect(TASK_FILTER_FIELDS.some((field) => field.field === "initiative_ids")).toBe(false);
  });

  it("gives every field at least one operator", () => {
    for (const field of TASK_FILTER_FIELDS) {
      expect(field.ops.length).toBeGreaterThan(0);
    }
  });

  it("resolves a known field and returns nothing for an unknown one", () => {
    expect(fieldSpec("assignee_ids")?.kind).toBe("member");
    expect(fieldSpec("not_a_field")).toBeUndefined();
  });
});
