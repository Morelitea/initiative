import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildPage, buildUser, communityCan } from "@/__tests__/factories";
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
  setInvalidationCommunity: vi.fn(),
  resetCommunityScopedQueries: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/offlineCache", () => ({
  isOfflineCacheEnabled: () => false,
  setGrantOnlyCommunityIds: vi.fn(),
  addGrantOnlyCommunityIds: vi.fn(),
  hydrateCommunityShard: vi.fn().mockResolvedValue(undefined),
  retainOnlyCommunities: vi.fn().mockResolvedValue(undefined),
}));

const currentUser = buildUser();
const refreshUser = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: currentUser, refreshUser }),
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => ({ isOnline: true }),
}));

import { CommunityProvider, useCommunities } from "./useCommunities";

const Probe = () => {
  const { activeCommunity } = useCommunities();
  return (
    <output>
      {JSON.stringify({
        content: activeCommunity?.grantAccessLevel,
        settings: activeCommunity?.grantSettingsLevel,
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
          data: buildPage([
            {
              community_id: 8,
              community_name: "Granted Community",
              purpose: "content",
              access_level: "read_write",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T21:00:00Z",
            },
            {
              community_id: 8,
              community_name: "Granted Community",
              purpose: "settings",
              access_level: "superadmin",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T22:00:00Z",
            },
          ]),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    render(
      <CommunityProvider>
        <Probe />
      </CommunityProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() =>
      expect(screen.getByText('{"content":"read_write","settings":"superadmin"}')).toBeVisible()
    );
  });

  it("reads every page of live grants", async () => {
    get.mockImplementation((path: string, config?: { params?: { page?: number } }) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/" && config?.params?.page === 1) {
        return Promise.resolve({ data: buildPage([], { has_next: true }) });
      }
      if (path === "/access-grants/" && config?.params?.page === 2) {
        return Promise.resolve({
          data: buildPage(
            [
              {
                community_id: 8,
                community_name: "Granted Community",
                purpose: "content",
                access_level: "read",
                is_live: true,
                requested_at: "2026-09-17T20:00:00Z",
                expires_at: "2026-09-17T21:00:00Z",
              },
            ],
            { page: 2, has_prev: true }
          ),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    render(
      <CommunityProvider>
        <Probe />
      </CommunityProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() =>
      expect(screen.getByText('{"content":"read","settings":null}')).toBeVisible()
    );
    expect(get).toHaveBeenCalledWith("/access-grants/", {
      params: { live: true, page: 2, page_size: 200 },
    });
  });

  it("keeps a settings grant alongside an ordinary membership", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") {
        return Promise.resolve({ data: [buildCommunity({ id: 8, role: "member" })] });
      }
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: buildPage([
            {
              community_id: 8,
              community_name: "Member Community",
              purpose: "settings",
              access_level: "superadmin",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T22:00:00Z",
            },
          ]),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    render(
      <CommunityProvider>
        <Probe />
      </CommunityProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() => expect(screen.getByText('{"settings":"superadmin"}')).toBeVisible());
  });

  it("takes what may be changed from the community's own entry", async () => {
    get.mockImplementation((path: string) => {
      if (path === "/communities/") return Promise.resolve({ data: [] });
      if (path === "/access-grants/") {
        return Promise.resolve({
          data: buildPage([
            {
              community_id: 8,
              community_name: "Granted Community",
              purpose: "settings",
              access_level: "admin",
              is_live: true,
              requested_at: "2026-09-17T20:00:00Z",
              expires_at: "2026-09-17T22:00:00Z",
            },
          ]),
        });
      }
      if (path === "/communities/8") {
        return Promise.resolve({
          data: buildCommunity({
            id: 8,
            role: "admin",
            can: communityCan("admin", {
              content: false,
              configure: false,
              administer_content: false,
            }),
            retention_days: 30,
          }),
        });
      }
      throw new Error(`Unexpected read: ${path}`);
    });

    const EntryProbe = () => {
      const { activeCommunity } = useCommunities();
      return (
        <output>
          {JSON.stringify({
            access: activeCommunity?.accessType,
            settings: activeCommunity?.grantSettingsLevel,
            can: activeCommunity?.can,
            retention: activeCommunity?.retention_days,
          })}
        </output>
      );
    };

    render(
      <CommunityProvider>
        <EntryProbe />
      </CommunityProvider>,
      { wrapper: withQueryClient() }
    );

    await waitFor(() =>
      expect(
        screen.getByText(
          JSON.stringify({
            access: "grant",
            settings: "admin",
            can: communityCan("admin", {
              content: false,
              configure: false,
              administer_content: false,
            }),
            retention: 30,
          })
        )
      ).toBeVisible()
    );
    expect(get).toHaveBeenCalledWith("/communities/8");
  });
});
