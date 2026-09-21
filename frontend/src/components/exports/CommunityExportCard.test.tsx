import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { CommunityExportCard } from "./CommunityExportCard";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/exportDownload", () => ({
  downloadExportArtifact: vi.fn(),
}));

const now = new Date();
const iso = (offsetMs: number) => new Date(now.getTime() + offsetMs).toISOString();

const job = (o: Record<string, unknown> = {}) => ({
  id: 7,
  guild_id: 1,
  created_by: 1,
  source: "guild",
  template_id: "backup",
  format: "zip",
  params: {},
  status: "done",
  error: null,
  delivered: false,
  expires_at: iso(6 * 86_400_000),
  created_at: iso(-3_600_000),
  updated_at: iso(-3_600_000),
  ...o,
});

const status = (o: Record<string, unknown> = {}) =>
  guildHttp.get("/exports/guild/status", () =>
    HttpResponse.json({
      cooldown_hours: 48,
      next_available_at: null,
      latest: null,
      latest_started_by: null,
      ...o,
    })
  );

describe("CommunityExportCard", () => {
  it("names who took the last export and offers it back", async () => {
    server.use(status({ latest: job(), latest_started_by: "Ada Lovelace" }));
    renderWithProviders(<CommunityExportCard />);

    expect(await screen.findByText(/Ada Lovelace/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
    expect(screen.getByText(/download expires/i)).toBeInTheDocument();
  });

  it("holds the door shut while the community is inside its cooldown", async () => {
    server.use(
      status({
        latest: job({ status: "queued", expires_at: null }),
        latest_started_by: "Ada Lovelace",
        next_available_at: iso(2 * 86_400_000),
      })
    );
    renderWithProviders(<CommunityExportCard />);

    expect(await screen.findByText(/next export available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export/i })).toBeDisabled();
    // A queued job has nothing to hand back yet.
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });

  it("says so when nobody has taken one", async () => {
    server.use(status());
    renderWithProviders(<CommunityExportCard />);

    expect(await screen.findByText(/nobody has exported this community yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export/i })).toBeEnabled();
  });
});
