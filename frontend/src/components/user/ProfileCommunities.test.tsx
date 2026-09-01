/**
 * Where a community chip on a profile takes you.
 *
 * A community's own pages need membership, so the destination depends on the
 * reader: in, for someone who is already there; the directory card, for
 * anyone else, which is the only place they can do anything about it.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { ProfileCommunities } from "./ProfileCommunities";

const mocks = vi.hoisted(() => ({ communities: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({ useUserCommunities: () => mocks.communities() }));

const guild = (overrides: Record<string, unknown> = {}) => ({
  id: 7,
  name: "Kobold Press",
  description: null,
  icon_url: null,
  categories: [],
  member_count: 3,
  online_count: 1,
  already_member: false,
  banner: { image_url: null, color: "", text_color: "#fff", text_align: "center", fade: "none" },
  ...overrides,
});

beforeEach(() => vi.clearAllMocks());

const render = () => renderPage(() => <ProfileCommunities handle="tinker0001" />);

describe("a community on a profile", () => {
  it("takes a member straight in", async () => {
    mocks.communities.mockReturnValue({ data: [guild({ already_member: true })] });
    render();

    expect(await screen.findByRole("link", { name: /Kobold Press/ })).toHaveAttribute(
      "href",
      "/c/7"
    );
  });

  it("takes everyone else to its card, not through a door they cannot open", async () => {
    mocks.communities.mockReturnValue({ data: [guild()] });
    render();

    const link = await screen.findByRole("link", { name: /Kobold Press/ });
    expect(link.getAttribute("href")).toContain("/communities");
    expect(link.getAttribute("href")).not.toContain("/c/7");
  });

  it("shows nothing at all when there are none", async () => {
    mocks.communities.mockReturnValue({ data: [] });
    const { container } = render();

    expect(container.querySelector("section")).toBeNull();
  });
});
