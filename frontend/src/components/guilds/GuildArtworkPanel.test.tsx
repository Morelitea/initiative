import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { GuildArtworkPanel } from "./GuildArtworkPanel";

const entitlements = (bannerImageEnabled: boolean) =>
  server.use(
    http.get("*/api/v1/guilds/:guildId/entitlements", () =>
      HttpResponse.json({ guild_id: 1, banner_image_enabled: bannerImageEnabled })
    )
  );

describe("GuildArtworkPanel", () => {
  it("offers a banner upload where the guild has artwork on its plan", async () => {
    entitlements(true);

    renderWithProviders(<GuildArtworkPanel guild={buildGuild({ id: 1, role: "admin" })} />);

    expect(await screen.findByLabelText("Banner")).toBeInTheDocument();
  });

  it("offers the colour alone where it does not", async () => {
    entitlements(false);

    renderWithProviders(<GuildArtworkPanel guild={buildGuild({ id: 1, role: "admin" })} />);

    await waitFor(() =>
      expect(screen.getByText(/plan doesn't include banner images/i)).toBeInTheDocument()
    );
    // The label stays — the banner still exists as a thing this guild has.
    expect(screen.queryByLabelText("Banner")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Banner colour")).toBeInTheDocument();
  });

  it("keeps showing a banner the guild already had", async () => {
    entitlements(false);

    const { container } = renderWithProviders(
      <GuildArtworkPanel
        guild={buildGuild({ id: 1, role: "admin", banner_url: "/api/v1/guilds/1/image/abc" })}
      />
    );

    await waitFor(() =>
      expect(container.querySelector('img[src="/api/v1/guilds/1/image/abc"]')).not.toBeNull()
    );
    expect(screen.getByRole("button", { name: "Remove banner" })).toBeInTheDocument();
  });

  it("always offers the icon — it is not part of that entitlement", async () => {
    entitlements(false);

    renderWithProviders(<GuildArtworkPanel guild={buildGuild({ id: 1, role: "admin" })} />);

    expect(await screen.findByLabelText("Icon")).toBeInTheDocument();
  });
});
