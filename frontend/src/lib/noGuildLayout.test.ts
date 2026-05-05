import { describe, expect, it } from "vitest";

import { chooseNoGuildLayout } from "./noGuildLayout";

/**
 * The route gate this helper drives is an auth boundary: a wrong
 * answer either traps a user with zero memberships out of their own
 * account-management surface, or admits a non-admin into the
 * platform-admin shell. Tests here pin the truth table.
 */
describe("chooseNoGuildLayout", () => {
  describe("when the user has at least one guild", () => {
    it("falls through to the main sidebar layout regardless of path / role", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: true,
          pathname: "/profile",
          isPlatformAdmin: false,
        })
      ).toBe("main");
      expect(
        chooseNoGuildLayout({
          hasGuilds: true,
          pathname: "/settings/admin",
          isPlatformAdmin: true,
        })
      ).toBe("main");
      expect(
        chooseNoGuildLayout({
          hasGuilds: true,
          pathname: "/projects/42",
          isPlatformAdmin: false,
        })
      ).toBe("main");
    });
  });

  describe("user-scoped settings routes (no guilds)", () => {
    it("renders the chromeless settings shell on /profile (any role)", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/profile",
          isPlatformAdmin: false,
        })
      ).toBe("shell");
    });

    it("matches /profile sub-paths like /profile/danger", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/profile/danger",
          isPlatformAdmin: false,
        })
      ).toBe("shell");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/profile/security",
          isPlatformAdmin: false,
        })
      ).toBe("shell");
    });

    it("does not match a partial-prefix collision like /profileX", () => {
      // ``startsWith("/profile/")`` (with the trailing slash) plus the
      // exact-match arm prevents this from leaking. Pin it so a future
      // refactor can't drop the slash and silently widen the gate.
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/profilex",
          isPlatformAdmin: false,
        })
      ).toBe("empty");
    });
  });

  describe("platform-admin settings routes (no guilds)", () => {
    it("renders the shell when the user is a platform admin", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/admin",
          isPlatformAdmin: true,
        })
      ).toBe("shell");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/admin/auth",
          isPlatformAdmin: true,
        })
      ).toBe("shell");
    });

    it("falls through to NoGuildState for non-admins", () => {
      // Non-admins shouldn't get the shell chrome for a route they
      // can't see content on — ``AdminSettingsLayout`` would redirect
      // them to /settings/guild anyway.
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/admin",
          isPlatformAdmin: false,
        })
      ).toBe("empty");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/admin/branding",
          isPlatformAdmin: false,
        })
      ).toBe("empty");
    });
  });

  describe("any other route (no guilds)", () => {
    it("returns empty so NoGuildState renders", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/",
          isPlatformAdmin: false,
        })
      ).toBe("empty");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/projects/1",
          isPlatformAdmin: true,
        })
      ).toBe("empty");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/guild",
          isPlatformAdmin: true,
        })
      ).toBe("empty");
    });
  });
});
