import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser } from "@/__tests__/factories";

const get = vi.fn();

vi.mock("@/api/client", () => ({
  apiClient: {
    get: (...args: unknown[]) => get(...args),
    post: vi.fn(),
    put: vi.fn(),
    defaults: { baseURL: "" },
  },
}));

vi.mock("@/api/query-keys", () => ({
  setInvalidationGuild: vi.fn(),
  resetGuildScopedQueries: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/offlineCache", () => ({
  isOfflineCacheEnabled: () => false,
  setGrantOnlyGuildIds: vi.fn(),
  addGrantOnlyGuildIds: vi.fn(),
  hydrateGuildShard: vi.fn().mockResolvedValue(undefined),
  retainOnlyGuilds: vi.fn().mockResolvedValue(undefined),
}));

const currentUser = buildUser();
const refreshUser = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: currentUser, refreshUser }),
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => ({ isOnline: true }),
}));

import { GuildProvider, useGuilds } from "./useGuilds";

const Probe = () => {
  const { activeGuild } = useGuilds();
  return (
    <output>
      {JSON.stringify({
        content: activeGuild?.grantAccessLevel,
        settings: activeGuild?.grantSettingsLevel,
      })}
    </output>
  );
};

describe("settings grants in the community switcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("preserves settings authority separately from content authority", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/guilds/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: [
            {
              guild_id: 8,
              guild_name: "Granted Community",
              purpose: "content",
              access_level: "read_write",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T21:00:00Z",
            },
            {
              guild_id: 8,
              guild_name: "Granted Community",
              purpose: "settings",
              access_level: "superadmin",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T22:00:00Z",
            },
          ],
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    render(
      <GuildProvider>
        <Probe />
      </GuildProvider>
    );

    await waitFor(() =>
      expect(screen.getByText('{"content":"read_write","settings":"superadmin"}')).toBeVisible()
    );
  });

  it("keeps a settings grant alongside an ordinary membership", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/guilds/") {
        return Promise.resolve({ data: [buildGuild({ id: 8, role: "member", is_admin: false })] });
      }
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: [
            {
              guild_id: 8,
              guild_name: "Member Community",
              purpose: "settings",
              access_level: "superadmin",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T22:00:00Z",
            },
          ],
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    render(
      <GuildProvider>
        <Probe />
      </GuildProvider>
    );

    await waitFor(() => expect(screen.getByText('{"settings":"superadmin"}')).toBeVisible());
  });
});
