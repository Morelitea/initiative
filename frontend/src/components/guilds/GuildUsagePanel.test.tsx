import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, guildCan } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

// Mutable state the mocked hooks read, so each test can vary billing config,
// the active guild, and the storage-usage response.
const state = vi.hoisted(() => ({
  guild: null as ReturnType<typeof Object> | null,
  billing: null as { url: string } | null,
  usage: { usage_bytes: 0 } as { usage_bytes: number } | undefined,
  usageError: false,
  usageEnabled: [] as boolean[],
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
  useReadStorageUsageApiV1CGuildIdStorageUsageGet: (
    _guildId: number,
    options: { query: { enabled: boolean } }
  ) => {
    state.usageEnabled.push(options.query.enabled);
    return { data: state.usage, isError: state.usageError };
  },
}));

import { GuildUsagePanel } from "./GuildUsagePanel";

// The panel is a guild-admin surface: it lives on the admin-gated settings
// page and renders fields the API sends to admins only, so every fixture here
// is an admin's payload.
describe("GuildUsagePanel", () => {
  beforeEach(() => {
    state.guild = buildGuild({
      id: 7,
      role: "superadmin",
      max_storage_bytes: 1000,
      max_users: 10,
      member_count: 4,
      tier_name: null,
    });
    state.billing = null;
    state.usage = { usage_bytes: 500 };
    state.usageError = false;
    state.usageEnabled = [];
  });

  it("renders storage and member usage against caps (FOSS, billing absent)", () => {
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.getByText("Storage")).toBeInTheDocument();
    expect(screen.getByText("Members")).toBeInTheDocument();
    // Members: 4 of 10 — the usage number renders from the guild's own row.
    expect(screen.getByText("4 of 10")).toBeInTheDocument();
  });

  it("shows no plan or portal UI, even to the seat of a billed deployment", () => {
    // The plan lives on the seat-only Billing tab (GuildBillingPanel); this
    // panel is usage alone.
    state.billing = { url: "https://billing.example.com" };
    state.guild = buildGuild({ id: 42, role: "superadmin", member_count: 4, tier_name: "gold" });
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.getByText("Storage")).toBeInTheDocument();
    expect(screen.queryByText("Upgrade")).not.toBeInTheDocument();
    expect(screen.queryByText("Manage billing")).not.toBeInTheDocument();
    expect(screen.queryByText(/Current plan/)).not.toBeInTheDocument();
  });

  it("renders unlimited caps without a hard limit", () => {
    state.guild = buildGuild({
      id: 7,
      role: "superadmin",
      max_storage_bytes: null,
      max_users: null,
      member_count: 3,
    });
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.getAllByText(/Unlimited/).length).toBeGreaterThan(0);
  });

  it("says the storage figure is unavailable rather than showing nothing stored", () => {
    // A refused or failed read is not zero bytes.
    state.usage = undefined;
    state.usageError = true;
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.getByText("Unavailable right now")).toBeInTheDocument();
    expect(screen.queryByText(/^0 B/)).not.toBeInTheDocument();
    // The member figure needs no request and still shows.
    expect(screen.getByText("4 of 10")).toBeInTheDocument();
  });

  it("shows no storage figure while it is still loading", () => {
    state.usage = undefined;
    renderWithProviders(<GuildUsagePanel />);
    expect(screen.queryByText(/of 1000 B|0 B/)).not.toBeInTheDocument();
    expect(screen.queryByText("Unavailable right now")).not.toBeInTheDocument();
  });

  it("asks for the figure on a settings grant too, which may read it", () => {
    // Support lent the seat sees the Usage tab without reaching the content.
    state.guild = {
      ...buildGuild({
        id: 7,
        role: "superadmin",
        can: guildCan("superadmin", { content: false }),
      }),
      accessType: "grant",
      grantSettingsLevel: "superadmin",
    };
    renderWithProviders(<GuildUsagePanel />);
    expect(state.usageEnabled.every(Boolean)).toBe(true);
    expect(screen.getByText(/500 B/)).toBeInTheDocument();
  });
});
