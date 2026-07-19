import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

// Mutable state the mocked hooks read, so each test can vary billing config,
// the active guild, and the storage-usage response.
const state = vi.hoisted(() => ({
  guild: null as ReturnType<typeof Object> | null,
  billing: null as { url: string } | null,
  usage: { usage_bytes: 0 } as { usage_bytes: number },
}));

vi.mock("@/hooks/useGuilds", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useGuilds")>("@/hooks/useGuilds");
  // Keep GuildContext (the render helper's provider imports it); override the hook.
  return { ...actual, useGuilds: () => ({ activeGuild: state.guild }) };
});
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: state.billing }),
}));
vi.mock("@/api/generated/storage/storage", () => ({
  useReadStorageUsageApiV1GGuildIdStorageUsageGet: () => ({ data: state.usage }),
}));
const mintMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/guilds/guilds", () => ({
  createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost: mintMock,
}));

import { GuildUsagePanel } from "./GuildUsagePanel";

describe("GuildUsagePanel", () => {
  beforeEach(() => {
    state.guild = buildGuild({
      id: 7,
      max_storage_bytes: 1000,
      max_users: 10,
      member_count: 4,
      tier_name: null,
    });
    state.billing = null;
    state.usage = { usage_bytes: 500 };
    mintMock.mockReset();
  });

  it("renders storage and member usage against caps (FOSS, billing absent)", () => {
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.getByText("Storage")).toBeInTheDocument();
    expect(screen.getByText("Members")).toBeInTheDocument();
    // Members: 4 of 10 — the usage number renders from the guild's own row.
    expect(screen.getByText("4 of 10")).toBeInTheDocument();
  });

  it("shows no billing/upgrade UI when no portal is configured", () => {
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.queryByText("Upgrade")).not.toBeInTheDocument();
    expect(screen.queryByText("Manage billing")).not.toBeInTheDocument();
    expect(screen.queryByText(/Current plan/)).not.toBeInTheDocument();
  });

  it("renders unlimited caps without a hard limit", () => {
    state.guild = buildGuild({
      id: 7,
      max_storage_bytes: null,
      max_users: null,
      member_count: 3,
    });
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.getAllByText(/Unlimited/).length).toBeGreaterThan(0);
  });

  it("member: anonymous upgrade link, no manage button", () => {
    state.billing = { url: "https://billing.example.com" };
    state.guild = buildGuild({
      id: 42,
      role: "member",
      max_storage_bytes: 1000,
      max_users: 10,
      member_count: 4,
      tier_name: "gold",
    });
    renderWithProviders(<GuildUsagePanel />);

    expect(screen.getByText("gold")).toBeInTheDocument();
    const upgrade = screen.getByText("Upgrade").closest("a");
    expect(upgrade).toHaveAttribute("href", "https://billing.example.com/upgrade?guild=42&lang=en");
    expect(screen.queryByText("Manage billing")).not.toBeInTheDocument();
  });

  it("admin: opens the portal with the minted token in the URL fragment", async () => {
    state.billing = { url: "https://billing.example.com" };
    state.guild = buildGuild({
      id: 42,
      role: "admin",
      max_storage_bytes: 1000,
      max_users: 10,
      member_count: 4,
      tier_name: "gold",
    });
    mintMock.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    renderWithProviders(<GuildUsagePanel />);
    await userEvent.click(screen.getByText("Manage billing"));

    expect(mintMock).toHaveBeenCalledWith(42);
    await waitFor(() =>
      expect(tab.location.href).toBe(
        "https://billing.example.com/manage?guild=42&lang=en#handoff=TOK"
      )
    );
    openSpy.mockRestore();
  });

  it("admin: falls back to the anonymous link if the mint fails", async () => {
    state.billing = { url: "https://billing.example.com" };
    state.guild = buildGuild({ id: 42, role: "admin", member_count: 1 });
    mintMock.mockRejectedValue(new Error("nope"));
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    renderWithProviders(<GuildUsagePanel />);
    await userEvent.click(screen.getByText("Upgrade"));

    await waitFor(() =>
      expect(tab.location.href).toBe("https://billing.example.com/upgrade?guild=42&lang=en")
    );
    openSpy.mockRestore();
  });
});
