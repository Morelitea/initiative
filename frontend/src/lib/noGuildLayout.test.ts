import { describe, expect, it } from "vitest";

import { chooseNoGuildLayout } from "./noGuildLayout";

/**
 * The route gate this helper drives is an auth boundary: a wrong
 * answer either traps a user with zero memberships out of their own
 * account-management surface, or admits someone without platform access into the
 * platform shell. Tests here pin the truth table.
 */
describe("chooseNoGuildLayout", () => {
  describe("when the user has at least one guild", () => {
    it("falls through to the main sidebar layout regardless of path / role", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: true,
          pathname: "/profile",
          canAccessPlatformAreas: false,
        })
      ).toBe("main");
      expect(
        chooseNoGuildLayout({
          hasGuilds: true,
          pathname: "/settings/operator",
          canAccessPlatformAreas: true,
        })
      ).toBe("main");
      expect(
        chooseNoGuildLayout({
          hasGuilds: true,
          pathname: "/projects/42",
          canAccessPlatformAreas: false,
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
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
    });

    it("matches /profile sub-paths like /profile/danger", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/profile/danger",
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/profile/security",
          canAccessPlatformAreas: false,
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
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
    });
  });

  describe("the community directory (no guilds)", () => {
    it("renders the chromeless shell so a guild-less user can join one", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/communities",
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
    });

    it("does not match a partial-prefix collision like /communitiesX", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/communitiesx",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
    });
  });

  describe("platform routes (no guilds)", () => {
    it("renders the shell when the user can reach the platform areas", () => {
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/operator",
          canAccessPlatformAreas: true,
        })
      ).toBe("shell");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/operator/users",
          canAccessPlatformAreas: true,
        })
      ).toBe("shell");
      // Platform settings (config) lives under /settings/platform now.
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/platform/branding",
          canAccessPlatformAreas: true,
        })
      ).toBe("shell");
    });

    it("falls through to NoGuildState without platform access", () => {
      // Someone without platform access shouldn't get the shell chrome for a route they
      // can't see content on — the layout would redirect them to
      // their own community settings anyway.
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/operator",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/platform/branding",
          canAccessPlatformAreas: false,
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
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/projects/1",
          canAccessPlatformAreas: true,
        })
      ).toBe("empty");
      expect(
        chooseNoGuildLayout({
          hasGuilds: false,
          pathname: "/settings/security",
          canAccessPlatformAreas: true,
        })
      ).toBe("empty");
    });
  });
});
