/**
 * The way to a person's profile, through the router the app ships.
 *
 * A profile is only useful if it is reachable: the generated route tree has to
 * serve `/u/{userId}` — outside the community tree, because a profile is public
 * and belongs to no community — and load the page from its own chunk. A test
 * that mounts the page component directly proves neither, so this one goes
 * through the tree and preloads the route's own component.
 */
import { createRouter } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/routeTree.gen";

import { buildUserProfile } from "./factories";
import { renderPage } from "./helpers/render";

const PROFILE_ROUTE_ID = "/_serverRequired/_authenticated/u/$handle";

const mocks = vi.hoisted(() => ({ profile: vi.fn() }));
vi.mock("@/hooks/useUsers", () => ({
  useUserProfile: (handle: string | null) => mocks.profile(handle),
}));

const router = createRouter({ routeTree });

const profilePage = async () => {
  const route = router.routesById[PROFILE_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

const renderProfile = async () => {
  const Page = await profilePage();
  return renderPage(Page, {
    initialRoute: "/u/$handle",
    routeParams: { handle: "tinker0042" },
  });
};

const answerWith = (profile: unknown) =>
  mocks.profile.mockReturnValue({ data: profile, isLoading: false });

beforeEach(() => {
  vi.clearAllMocks();
  answerWith(buildUserProfile());
});

describe("a member's profile", () => {
  it("is an address the shipped route tree serves, keyed by handle", () => {
    const matches = router.matchRoutes(
      { pathname: "/u/tinker0042", search: {} },
      { preload: true }
    );
    expect(String(matches.at(-1)?.routeId)).toBe(PROFILE_ROUTE_ID);
  });

  it("asks for the handle in the address, not an id", async () => {
    await renderProfile();
    await screen.findByRole("heading");

    expect(mocks.profile).toHaveBeenCalledWith("tinker0042");
  });

  it("leads with the handle, and shows the line they wrote", async () => {
    // The handle is the name in this product — a profile carries no real name
    // at all, so it is the heading rather than a subtitle under one.
    answerWith(
      buildUserProfile({
        username: "tinker",
        discriminator: 42,
        custom_status: { emoji: "🎲", text: "rolling for initiative" },
      })
    );
    await renderProfile();

    expect(await screen.findByRole("heading", { name: /tinker/ })).toBeInTheDocument();
    expect(screen.getByTitle("tinker#0042")).toBeInTheDocument();
    expect(screen.getByText("rolling for initiative")).toBeInTheDocument();
  });

  it("says when someone has Initiative open", async () => {
    answerWith(buildUserProfile({ online: true }));
    await renderProfile();

    expect(await screen.findByText("Online")).toBeInTheDocument();
  });

  it("wears the decorations it can draw, and ignores the ones it cannot", async () => {
    answerWith(
      buildUserProfile({
        profile_decorations: {
          banner: "core.aurora",
          frame: "core.gold",
          badges: ["core.founder", "thirdparty.unknown"],
        },
      })
    );
    const { container } = await renderProfile();

    expect(await screen.findByAltText("Founder")).toHaveAttribute(
      "src",
      "/decorations/badges/core-founder.svg"
    );
    // The frame is worn over the picture and says nothing, so it is hidden
    // from assistive technology and found by its source instead.
    expect(container.querySelector('img[src="/decorations/frames/core-gold.svg"]')).not.toBeNull();
    expect(
      container.querySelector('[style*="/decorations/banners/core-aurora.svg"]')
    ).not.toBeNull();
  });

  it("says so when there is nobody behind the address", async () => {
    answerWith(undefined);
    await renderProfile();

    expect(await screen.findByText("No profile here")).toBeInTheDocument();
  });
});
