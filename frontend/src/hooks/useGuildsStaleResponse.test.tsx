/**
 * A reply that belongs to somebody else.
 *
 * Reads outlive the person they were made for: signing out, or switching
 * account, does not cancel a request already in the air. Acting on one of those
 * late replies used to be a cosmetic problem — a stale switcher. It stopped
 * being cosmetic once the membership list started driving what gets deleted
 * from this device, because then the previous user's memberships decide what
 * the current one keeps.
 */
import { render, waitFor } from "@testing-library/react";
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

const retainOnlyGuilds = vi.fn().mockResolvedValue(undefined);
const saveOfflineGuilds = vi.fn();

vi.mock("@/lib/offlineCache", () => ({
  isOfflineCacheEnabled: () => true,
  setGrantOnlyGuildIds: vi.fn(),
  addGrantOnlyGuildIds: vi.fn(),
  hydrateGuildShard: vi.fn().mockResolvedValue(undefined),
  retainOnlyGuilds: (...args: unknown[]) => retainOnlyGuilds(...args),
}));

vi.mock("@/lib/offlineSession", () => ({
  currentServerKey: () => "https://initiative.example",
  isNoAnswerError: () => false,
  readOfflineGuilds: () => null,
  saveOfflineGuilds: (...args: unknown[]) => saveOfflineGuilds(...args),
}));

let currentUser: ReturnType<typeof buildUser> | null = null;

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: currentUser, refreshUser: vi.fn() }),
}));

vi.mock("@/hooks/useNetworkStatus", () => ({
  useNetworkStatus: () => ({ isOnline: true }),
}));

import { GuildProvider } from "./useGuilds";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

const userA = buildUser();
const userB = buildUser();

beforeEach(() => {
  vi.clearAllMocks();
  currentUser = null;
});

describe("a guild list that arrives for the wrong account", () => {
  it("is not allowed to prune this device against the previous user", async () => {
    const first = deferred<{ data: unknown }>();
    get.mockReturnValueOnce(first.promise);

    currentUser = userA;
    const view = render(
      <GuildProvider>
        <div />
      </GuildProvider>
    );

    await waitFor(() => expect(get).toHaveBeenCalledWith("/guilds/"));

    // Somebody else is here now, and their own read is already under way.
    currentUser = userB;
    get.mockResolvedValue({ data: [buildGuild({ id: 99 })] });
    view.rerender(
      <GuildProvider>
        <div />
      </GuildProvider>
    );

    // Only now does the first account's reply come back.
    first.resolve({ data: [buildGuild({ id: 1 }), buildGuild({ id: 2 })] });

    await waitFor(() => expect(retainOnlyGuilds).toHaveBeenCalled());

    // Every prune must be for the account that is actually here.
    for (const call of retainOnlyGuilds.mock.calls) {
      expect(call[1]).not.toEqual(expect.arrayContaining([1, 2]));
    }
    // And the stale list is not written down as what this device should hold.
    for (const call of saveOfflineGuilds.mock.calls) {
      const ids = (call[0] as Array<{ id: number }>).map((guild) => guild.id);
      expect(ids).not.toContain(1);
    }
  });
});
