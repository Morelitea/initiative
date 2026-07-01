import { describe, expect, it } from "vitest";

import { canManageSharing } from "./BulkAccessBar";

describe("canManageSharing", () => {
  it("is false for an empty selection", () => {
    expect(canManageSharing([])).toBe(false);
  });

  it("is true only when every item is write or owner", () => {
    expect(
      canManageSharing([{ my_permission_level: "owner" }, { my_permission_level: "write" }])
    ).toBe(true);
  });

  it("is false when any item is read-only or unknown", () => {
    expect(
      canManageSharing([{ my_permission_level: "owner" }, { my_permission_level: "read" }])
    ).toBe(false);
    expect(canManageSharing([{ my_permission_level: null }])).toBe(false);
  });
});
