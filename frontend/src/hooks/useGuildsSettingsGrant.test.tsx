import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser, guildCan } from "@/__tests__/factories";
import { createTestQueryClient } from "@/__tests__/helpers/render";

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

/** The provider reads its list through React Query, so each test gets a client. */
const withQueryClient = () => {
  const client = createTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe("settings grants in the community switcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("preserves settings authority separately from content authority", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
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
      </GuildProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() =>
      expect(screen.getByText('{"content":"read_write","settings":"superadmin"}')).toBeVisible()
    );
  });

  it("keeps a settings grant alongside an ordinary membership", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") {
        return Promise.resolve({ data: [buildGuild({ id: 8, role: "member" })] });
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
      </GuildProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() => expect(screen.getByText('{"settings":"superadmin"}')).toBeVisible());
  });

  it("takes what may be changed from the community's own entry", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: [
            {
              guild_id: 8,
              guild_name: "Granted Community",
              purpose: "settings",
              access_level: "admin",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T22:00:00Z",
            },
          ],
        });
      }
      if (path === "/communities/8") {
        return Promise.resolve({
          data: buildGuild({
            id: 8,
            role: "admin",
            can: guildCan("admin", { content: false, configure: false, administer_content: false }),
            retention_days: 30,
          }),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    const EntryProbe = () => {
      const { activeGuild } = useGuilds();
      return (
        <output>
          {JSON.stringify({
            access: activeGuild?.accessType,
            settings: activeGuild?.grantSettingsLevel,
            can: activeGuild?.can,
            retention: activeGuild?.retention_days,
          })}
        </output>
      );
    };

    render(
      <GuildProvider>
        <EntryProbe />
      </GuildProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() =>
      expect(
        screen.getByText(
          JSON.stringify({
            access: "grant",
            settings: "admin",
            can: guildCan("admin", { content: false, configure: false, administer_content: false }),
            retention: 30,
          })
        )
      ).toBeVisible()
    );
    expect(get).toHaveBeenCalledWith("/communities/8");
  });
});
