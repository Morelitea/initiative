import { describe, expect, it } from "vitest";

import { BadgeKind } from "@/api/generated/initiativeAPI.schemas";
import { BADGE_MENU } from "@/components/ui/editor/plugins/picker/badge-picker-plugin";

describe("the insert menu", () => {
  it("offers every badge the server answers", () => {
    // The pairs are generated from the server's registry, so adding one there
    // fails here until it is offered rather than being quietly unreachable.
    expect(Object.keys(BADGE_MENU).sort()).toEqual(Object.values(BadgeKind).sort());
  });

  it("gives each one a name and something to search it by", () => {
    for (const entry of Object.values(BADGE_MENU)) {
      expect(entry.labelKey).toMatch(/^badges\./);
      expect(entry.keywords.length).toBeGreaterThan(0);
    }
  });
});
