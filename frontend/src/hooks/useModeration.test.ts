/**
 * Who is offered the moderation surface.
 *
 * The standing is the flag a role carries, not the name of the built-in role:
 * a community may rename Moderator or define its own role with Full access,
 * and both must reach it. Project Manager deliberately must not — it manages
 * the initiative without reaching past sharing.
 */
import { describe, expect, it } from "vitest";

import { buildInitiative, buildInitiativeMember, buildUser } from "@/__tests__/factories";
import { canModerate } from "@/hooks/useModeration";

const withMember = (overrides: Record<string, unknown>) => {
  const user = buildUser();
  const initiative = buildInitiative({
    members: [buildInitiativeMember({ user, ...overrides })],
  });
  return { user, initiative };
};

describe("canModerate", () => {
  it("admits a member whose role carries Full access", () => {
    const { user, initiative } = withMember({ override_share_restrictions: true });
    expect(canModerate(initiative, user.id, false)).toBe(true);
  });

  it("does not admit a manager without it", () => {
    // Project Manager: is_manager, no Full access.
    const { user, initiative } = withMember({
      is_manager: true,
      override_share_restrictions: false,
    });
    expect(canModerate(initiative, user.id, false)).toBe(false);
  });

  it("does not admit an ordinary member", () => {
    const { user, initiative } = withMember({ override_share_restrictions: false });
    expect(canModerate(initiative, user.id, false)).toBe(false);
  });

  it("admits a guild admin who is not in the initiative at all", () => {
    const initiative = buildInitiative({ members: [] });
    expect(canModerate(initiative, 999, true)).toBe(true);
  });

  it("admits nobody when there is no reader", () => {
    const initiative = buildInitiative({ members: [] });
    expect(canModerate(initiative, undefined, false)).toBe(false);
  });

  it("reads the flag rather than the role name", () => {
    // A community renamed its moderators; the standing is unchanged.
    const { user, initiative } = withMember({
      role_name: "keepers_of_the_peace",
      override_share_restrictions: true,
    });
    expect(canModerate(initiative, user.id, false)).toBe(true);
  });
});
