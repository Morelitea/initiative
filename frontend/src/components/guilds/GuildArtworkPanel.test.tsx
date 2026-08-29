import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    expect(screen.getByLabelText("Banner fill")).toBeInTheDocument();
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

  it("previews the banner once, showing the fill where there is no artwork", async () => {
    entitlements(true);

    const { container } = renderWithProviders(
      <GuildArtworkPanel
        guild={buildGuild({ id: 1, role: "admin", name: "Ravenloft", banner_color: "#2a9d8f" })}
      />
    );

    await screen.findByLabelText("Banner fill");
    // One preview, not one per control — the guild is named once, on the fill.
    const name = screen.getByText("Ravenloft");
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(name.parentElement).toHaveStyle({ backgroundColor: "rgb(42, 157, 143)" });
  });

  it("saves a text colour the moment it is chosen, with no confirm step", async () => {
    entitlements(true);
    const patched: unknown[] = [];
    server.use(
      http.patch("*/api/v1/guilds/:guildId", async ({ request }) => {
        const body = await request.json();
        patched.push(body);
        return HttpResponse.json(
          buildGuild({ id: 1, role: "admin", name: "Ravenloft", banner_text_color: "#000000" })
        );
      })
    );

    renderWithProviders(
      <GuildArtworkPanel guild={buildGuild({ id: 1, role: "admin", name: "Ravenloft" })} />
    );

    await userEvent.click(await screen.findByRole("button", { name: "Dark" }));

    // The preview answers immediately...
    expect(screen.getByText("Ravenloft")).toHaveStyle({ color: "rgb(0, 0, 0)" });
    // ...and so does the server, without anyone pressing anything else.
    await waitFor(() => expect(patched).toHaveLength(1));
    expect(patched[0]).toMatchObject({ banner_text_color: "#000000" });
    expect(screen.queryByRole("button", { name: /use this colour/i })).not.toBeInTheDocument();
  });

  it("offers banner text as two colours, never a picker", async () => {
    entitlements(true);

    renderWithProviders(<GuildArtworkPanel guild={buildGuild({ id: 1, role: "admin" })} />);

    // Black or white only: a fill the guild picked, or artwork of any colour,
    // stays readable only at one end of the scale or the other.
    expect(await screen.findByRole("button", { name: "Light" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByLabelText("Banner text")).not.toBeInTheDocument();
  });

  it("always offers the icon — it is not part of that entitlement", async () => {
    entitlements(false);

    renderWithProviders(<GuildArtworkPanel guild={buildGuild({ id: 1, role: "admin" })} />);

    expect(await screen.findByLabelText("Icon")).toBeInTheDocument();
  });
});
