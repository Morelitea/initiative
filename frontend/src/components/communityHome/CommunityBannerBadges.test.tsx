/**
 * The badge that counts a community's members.
 *
 * It used to say how many people were here and go nowhere, which is the whole
 * reason the roster was hard to find. What matters now is that the count is
 * the way in.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { CommunityBannerBadges } from "./CommunityBannerBadges";

const setup = (props: Partial<Parameters<typeof CommunityBannerBadges>[0]> = {}) =>
  renderPage(() => (
    <CommunityBannerBadges communityId={7} memberCount={12} onlineCount={0} ink="#fff" {...props} />
  ));

describe("the banner badges", () => {
  it("sends the member count to that community's roster", async () => {
    setup();

    expect(await screen.findByRole("link", { name: /12 members/i })).toHaveAttribute(
      "href",
      "/c/7/members"
    );
  });

  it("says nothing about nobody being online", async () => {
    setup();

    expect(await screen.findByRole("link", { name: /12 members/i })).toBeInTheDocument();
    expect(screen.queryByText(/online/i)).toBeNull();
  });
});
