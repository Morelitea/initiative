import { screen } from "@testing-library/react";
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
  useReadStorageUsageApiV1CGuildIdStorageUsageGet: () => ({ data: state.usage }),
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
});
