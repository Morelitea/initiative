import { describe, expect, it } from "vitest";

import { keptView, LIST, NO_PART_VIEW, partOf, sanitizeListView, viewKey } from "./useListView";

const spec = {
  key: viewKey(4, "initiative", 2, "files"),
  read: (raw: unknown) => raw as { tag_ids: number[] },
  defaults: { filters: { tag_ids: [] }, ...NO_PART_VIEW, sorting: [{ id: "name", desc: false }] },
  carryOver: () => ({
    layout: "grid",
    parts: { [LIST]: { sorting: [{ id: "updated_at", desc: true }] } },
  }),
};

describe("a person's view of a list", () => {
  it("is kept under the community, then what names the list", () => {
    expect(spec.key).toBe("view:4:initiative:2:files");
  });

  it("reads what is kept, else what an older release kept", () => {
    const kept = { layout: "list", parts: { [LIST]: { filters: { tag_ids: [7] } } } };
    expect(keptView({ [spec.key]: kept }, spec).view.layout).toBe("list");
    expect(keptView({}, spec).view.layout).toBe("grid");
  });

  it("fills what a part keeps with the list's defaults", () => {
    const view = keptView({}, spec).view;
    expect(partOf(view, LIST, spec)).toEqual({
      filters: { tag_ids: [] },
      sorting: [{ id: "updated_at", desc: true }],
      grouping: [],
      columns: {},
    });
  });

  it("drops what has the wrong type rather than breaking the list", () => {
    const view = sanitizeListView({
      layout: 3,
      parts: { [LIST]: { sorting: [{ id: 1 }, { id: "name", desc: true }], grouping: "x" } },
    });
    expect(view.layout).toBeNull();
    expect(partOf(view, LIST, spec)).toMatchObject({
      sorting: [{ id: "name", desc: true }],
      grouping: [],
    });
  });
});
