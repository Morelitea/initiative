import { describe, expect, it } from "vitest";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import { readConditions } from "@/lib/widgets/conditions";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import {
  bindingScope,
  describeConditions,
  describeLeaf,
  EMPTY_LABELS,
  type EntityLabels,
  type ProvenanceT,
} from "@/lib/widgets/provenance";

/** A `t` that echoes its key and interpolations, so these assert on which
 *  string was chosen rather than on the English wording of it. */
const t = ((key: string, options?: Record<string, unknown>) => {
  if (!options) return key;
  const { defaultValue: _default, ...rest } = options;
  const parts = Object.entries(rest).map(([name, value]) => `${name}=${value}`);
  return parts.length ? `${key}(${parts.join(",")})` : key;
}) as unknown as ProvenanceT;

const formatDate = (epoch: number) => new Date(epoch).toISOString().slice(0, 10);

const labels = (overrides: Partial<EntityLabels> = {}): EntityLabels => ({
  ...EMPTY_LABELS,
  project: new Map(),
  calendar: new Map(),
  counterGroup: new Map(),
  counter: new Map(),
  document: new Map(),
  member: new Map(),
  tag: new Map(),
  ready: true,
  ...overrides,
});

const binding = (partial: Partial<WidgetBinding> & { source: WidgetSource }): WidgetBinding =>
  partial as WidgetBinding;

describe("bindingScope", () => {
  it("names an id the viewer can resolve", () => {
    const scope = bindingScope(
      binding({ source: "tasks", project_id: 7 }),
      labels({ project: new Map([[7, "Website redesign"]]) })
    );
    expect(scope).toEqual([{ key: "project_id", label: "Website redesign", restricted: false }]);
  });

  it("marks an id the viewer cannot resolve as restricted, carrying no name", () => {
    const scope = bindingScope(binding({ source: "tasks", project_id: 7 }), labels());
    expect(scope).toEqual([{ key: "project_id", label: undefined, restricted: true }]);
  });

  it("does not call anything restricted while its lookup is still loading", () => {
    // An id that has not resolved *yet* is not an id that will not resolve.
    const scope = bindingScope(
      binding({ source: "tasks", project_id: 7 }),
      labels({ ready: false })
    );
    expect(scope[0].restricted).toBe(false);
  });

  it("omits a parameter with no value — the default is not a fact worth stating", () => {
    expect(bindingScope(binding({ source: "tasks" }), labels())).toEqual([]);
  });

  it("resolves both halves of a counter binding", () => {
    const scope = bindingScope(
      binding({ source: "counter", counter_group_id: 2, counter_id: 5 }),
      labels({
        counterGroup: new Map([[2, "Release readiness"]]),
        counter: new Map([[5, "Blockers"]]),
      })
    );
    expect(scope.map((chip) => chip.label)).toEqual(["Release readiness", "Blockers"]);
  });
});

describe("describeLeaf", () => {
  it("names values the viewer can resolve", () => {
    const [leaf] = readConditions([{ field: "assignee_ids", op: "in_", value: [4] }]);
    const line = describeLeaf(
      leaf as never,
      labels({ member: new Map([[4, "Ada"]]) }),
      t,
      formatDate
    );
    expect(line).toContain("Ada");
  });

  it("counts values it cannot resolve instead of naming or dropping them", () => {
    const [leaf] = readConditions([{ field: "assignee_ids", op: "in_", value: [4, 9] }]);
    const line = describeLeaf(
      leaf as never,
      labels({ member: new Map([[4, "Ada"]]) }),
      t,
      formatDate
    );
    expect(line).toContain("Ada");
    expect(line).toContain("hiddenValues");
    expect(line).not.toContain("9");
  });

  it("resolves the DSL's own token for the requesting user without a lookup", () => {
    const [leaf] = readConditions([{ field: "assignee_ids", op: "in_", value: ["me"] }]);
    expect(describeLeaf(leaf as never, labels(), t, formatDate)).toContain("provenance.me");
  });

  it("uses the negated phrasing when the comparison is inverted", () => {
    const [leaf] = readConditions([{ field: "priority", op: "in_", value: ["low"], negate: true }]);
    expect(describeLeaf(leaf as never, labels(), t, formatDate)).toContain("filterPhrase.not_in_");
  });

  it("reads an emptiness check without a value", () => {
    const [leaf] = readConditions([{ field: "due_date", op: "is_null" }]);
    expect(describeLeaf(leaf as never, labels(), t, formatDate)).toContain("filterPhrase.is_null");
  });

  it("says a relative date in days rather than as an instant", () => {
    const [leaf] = readConditions([{ field: "due_date", op: "lt", value: { relative: 30 } }]);
    const line = describeLeaf(leaf as never, labels(), t, formatDate);
    expect(line).toContain("provenance.inDays(count=30)");
  });

  it("formats an absolute date with the caller's formatter", () => {
    const [leaf] = readConditions([{ field: "due_date", op: "lt", value: "2026-09-30T00:00:00Z" }]);
    expect(describeLeaf(leaf as never, labels(), t, formatDate)).toContain("2026-09-30");
  });
});

describe("describeConditions", () => {
  it("gives one line per top-level comparison", () => {
    const nodes = readConditions([
      { field: "priority", op: "in_", value: ["high"] },
      { field: "due_date", op: "is_null" },
    ]);
    expect(describeConditions(nodes, labels(), t, formatDate)).toHaveLength(2);
  });

  it("keeps a group on one line, joined by its own logic word", () => {
    const nodes = readConditions([
      {
        logic: "or",
        conditions: [
          { field: "title", op: "ilike", value: "a" },
          { field: "title", op: "ilike", value: "b" },
        ],
      },
    ]);
    const [line] = describeConditions(nodes, labels(), t, formatDate);
    expect(line).toContain("provenance.or");
  });

  it("is empty when there are no conditions", () => {
    expect(describeConditions([], labels(), t, formatDate)).toEqual([]);
  });
});
