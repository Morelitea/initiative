import { describe, expect, it } from "vitest";

import { chooseNoCommunityLayout } from "./noCommunityLayout";

/**
 * The route gate this helper drives is an auth boundary: a wrong
 * answer either traps a user with zero memberships out of their own
 * account-management surface, or admits someone without platform access into the
 * platform shell. Tests here pin the truth table.
 */
describe("chooseNoCommunityLayout", () => {
  describe("when the user has at least one community", () => {
    it("falls through to the main sidebar layout regardless of path / role", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: true,
          pathname: "/profile",
          canAccessPlatformAreas: false,
        })
      ).toBe("main");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: true,
          pathname: "/settings/operator",
          canAccessPlatformAreas: true,
        })
      ).toBe("main");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: true,
          pathname: "/projects/42",
          canAccessPlatformAreas: false,
        })
      ).toBe("main");
    });
  });

  describe("user-scoped settings routes (no communities)", () => {
    it("renders the chromeless settings shell on /profile (any role)", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/profile",
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
    });

    it("matches /profile sub-paths like /profile/danger", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/profile/danger",
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/profile/security",
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
    });

    it("does not match a partial-prefix collision like /profileX", () => {
      // ``startsWith("/profile/")`` (with the trailing slash) plus the
      // exact-match arm keeps this from matching. Pin it so a future
      // refactor can't drop the slash and silently widen the gate.
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/profilex",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
    });
  });

  describe("the community directory (no communities)", () => {
    it("renders the chromeless shell so a community-less user can join one", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/communities",
          canAccessPlatformAreas: false,
        })
      ).toBe("shell");
    });

    it("does not match a partial-prefix collision like /communitiesX", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/communitiesx",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
    });
  });

  describe("the billing forwarder (no communities)", () => {
    it("renders the shell on a community's billing link, and nowhere else under it", () => {
      const at = (pathname: string) =>
        chooseNoCommunityLayout({ hasCommunities: false, pathname, canAccessPlatformAreas: false });
      expect(at("/c/7/billing")).toBe("shell");
      expect(at("/c/7/billing/x")).toBe("empty");
      expect(at("/c/x/billing")).toBe("empty");
      expect(at("/c/7/settings")).toBe("empty");
    });
  });

  describe("platform routes (no communities)", () => {
    it("renders the shell when the user can reach the platform areas", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/settings/operator",
          canAccessPlatformAreas: true,
        })
      ).toBe("shell");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/settings/operator/users",
          canAccessPlatformAreas: true,
        })
      ).toBe("shell");
      // Platform settings (config) lives under /settings/platform now.
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/settings/platform/branding",
          canAccessPlatformAreas: true,
        })
      ).toBe("shell");
    });

    it("falls through to NoCommunityState without platform access", () => {
      // Someone without platform access shouldn't get the shell chrome for a route they
      // can't see content on — the layout would redirect them to
      // their own community settings anyway.
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/settings/operator",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/settings/platform/branding",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
    });
  });

  describe("any other route (no communities)", () => {
    it("returns empty so NoCommunityState renders", () => {
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/",
          canAccessPlatformAreas: false,
        })
      ).toBe("empty");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/projects/1",
          canAccessPlatformAreas: true,
        })
      ).toBe("empty");
      expect(
        chooseNoCommunityLayout({
          hasCommunities: false,
          pathname: "/settings/security",
          canAccessPlatformAreas: true,
        })
      ).toBe("empty");
    });
  });
});
