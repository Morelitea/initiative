import { describe, expect, it } from "vitest";

import { FALLBACK_PROVIDER_ICON, providerIcon } from "@/lib/authProviderIcons";
import { PROVIDER_PRESETS } from "@/lib/authProviderPresets";

describe("provider marks", () => {
  it("gives every preset something to draw", () => {
    // Nothing in the grid renders blank, whether the mark is its own or the
    // stand-in. (A mark is a forwardRef component, so an object, not a
    // function — assert it is renderable rather than guessing its shape.)
    for (const preset of PROVIDER_PRESETS) {
      expect(providerIcon(preset.key), preset.key).toBeTruthy();
    }
  });

  it("has a mark of its own for the providers simple-icons carries", () => {
    const carried = ["google", "okta", "auth0", "keycloak", "authentik", "authelia", "custom"];
    for (const key of carried) {
      expect(providerIcon(key), key).not.toBe(FALLBACK_PROVIDER_ICON);
    }
  });

  it("falls back for the three it does not carry, and for anything unknown", () => {
    // simple-icons has no Entra, Zitadel or Pocket ID mark. They read as their
    // names, which is most of the job; see the note in authProviderIcons.ts.
    for (const key of ["microsoft", "zitadel", "pocket-id", "made-up", null, undefined]) {
      expect(providerIcon(key), String(key)).toBe(FALLBACK_PROVIDER_ICON);
    }
  });
});
