/**
 * Where a community card on a profile takes you.
 *
 * A community's own pages need membership, so the destination depends on the
 * reader: in, for someone who is already there; the directory card, for
 * anyone else, which is the only place they can do anything about it.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { ProfileCommunities } from "./ProfileCommunities";

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

const render = (...communities: ReturnType<typeof guild>[]) =>
  renderPage(() => <ProfileCommunities communities={communities} />);

describe("a community on a profile", () => {
  it("takes a member straight in", async () => {
    render(guild({ already_member: true }));

    expect(await screen.findByRole("link", { name: /Kobold Press/ })).toHaveAttribute(
      "href",
      "/c/7"
    );
  });

  it("takes everyone else to its card, not through a door they cannot open", async () => {
    render(guild());

    const link = await screen.findByRole("link", { name: /Kobold Press/ });
    expect(link.getAttribute("href")).toContain("/communities");
    expect(link.getAttribute("href")).not.toContain("/c/7");
  });

  it("says who is there now and how many there are in all", async () => {
    render(guild({ member_count: 12, online_count: 3 }));

    expect(await screen.findByText("3 online")).toBeInTheDocument();
    expect(screen.getByText("12 members")).toBeInTheDocument();
  });

  it("says nothing about who is online in an empty room", async () => {
    render(guild({ member_count: 12, online_count: 0 }));

    expect(await screen.findByText("12 members")).toBeInTheDocument();
    expect(screen.queryByText(/online/)).not.toBeInTheDocument();
  });
});
