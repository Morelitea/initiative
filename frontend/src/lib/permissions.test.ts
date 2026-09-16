import { describe, expect, it } from "vitest";

import { isGuildAdminRole } from "./permissions";

describe("who carries a guild admin's authority", () => {
  it("counts the seat above admin as one", () => {
    expect(isGuildAdminRole("admin")).toBe(true);
    expect(isGuildAdminRole("security_admin")).toBe(true);
  });

  it("does not count a member", () => {
    expect(isGuildAdminRole("member")).toBe(false);
  });

  it("does not count a grant standing in for a membership", () => {
    expect(isGuildAdminRole("support")).toBe(false);
  });

  it("answers no when there is no guild in hand", () => {
    expect(isGuildAdminRole(undefined)).toBe(false);
    expect(isGuildAdminRole(null)).toBe(false);
  });
});
