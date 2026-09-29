/**
 * Capability drift tests — the hand-written mirror in `permissions.ts` must
 * name exactly the capabilities the API exposes. A capability added, renamed
 * or retired on the backend fails here instead of leaving a constant that
 * gates nothing, or a capability no UI can ask for.
 *
 * Mirrors the backend's app/core/capabilities.py via the generated enum.
 */
import { describe, expect, it } from "vitest";

import { ownerCan, writerCan } from "@/__tests__/factories";
import { capabilitiesForRole } from "@/__tests__/factories/user.factory";
import { Capability as ApiCapability, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { Capability, everyCan } from "@/lib/permissions";

describe("capability mirror", () => {
  it("covers exactly the generated Capability enum", () => {
    expect(Object.values(Capability).sort()).toEqual(Object.values(ApiCapability).sort());
  });

  it("the test factory's role presets name only real capabilities", () => {
    const known = Object.values(ApiCapability) as string[];
    for (const role of Object.values(UserRole)) {
      for (const capability of capabilitiesForRole(role)) {
        expect(known, `${role} preset names unknown capability ${capability}`).toContain(
          capability
        );
      }
    }
  });
});

describe("everyCan", () => {
  it("is false for an empty selection", () => {
    expect(everyCan([], "share")).toBe(false);
  });

  it("asks every item for the one action", () => {
    const items = [{ can: ownerCan() }, { can: writerCan() }];
    expect(everyCan(items, "edit")).toBe(true);
    expect(everyCan(items, "share")).toBe(false);
  });
});
