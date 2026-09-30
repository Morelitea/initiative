import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";

import { useCollaboration } from "./useCollaboration";

const calls: string[] = [];
const provider = {
  doc: {},
  connected: true,
  on: vi.fn(),
  onCollaborators: vi.fn(),
  onError: vi.fn(),
  connect: vi.fn(),
  unsentEdits: vi.fn((): { update: Uint8Array; stateVector: Uint8Array } | null => null),
  handedOver: vi.fn(),
  sendContent: vi.fn((content: unknown) => calls.push(`send ${JSON.stringify(content)}`)),
  destroy: vi.fn(() => calls.push("destroy")),
};

vi.mock("./useAuth", () => ({ useAuth: () => ({ token: "t", user: { id: 1 } }) }));
vi.mock("./useGuilds", () => ({ useGuilds: () => ({ activeGuildId: 1 }) }));
vi.mock("@/lib/wsUrl", () => ({ buildGuildWsUrl: (_g: number, path: string) => `ws://x/${path}` }));
vi.mock("@/lib/yjs/CollaborationProvider", () => ({
  getLiveProvider: () => null,
  getOrCreateProvider: () => provider,
}));

describe("useCollaboration", () => {
  beforeEach(() => {
    calls.length = 0;
    provider.connected = true;
    provider.unsentEdits.mockReturnValue(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("hands the room the last rendering before the socket closes", () => {
    const { result, unmount } = renderHook(() =>
      useCollaboration({ socketPath: "documents/7/collaborate", finalContent: () => ({ a: 1 }) })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    unmount();
    expect(calls).toEqual(['send {"a":1}', "destroy"]);
  });

  it("sends nothing when there is nothing to hand over", () => {
    const { result, unmount } = renderHook(() =>
      useCollaboration({ socketPath: "documents/7/collaborate", finalContent: () => undefined })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    unmount();
    expect(calls).toEqual(["destroy"]);
  });

  it("hands the edits made without a socket to the room over REST", async () => {
    provider.connected = false;
    provider.unsentEdits.mockReturnValue({
      update: new Uint8Array([1, 2]),
      stateVector: new Uint8Array([3]),
    });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({});

    const { result, unmount } = renderHook(() =>
      useCollaboration({ socketPath: "documents/7/collaborate", finalContent: () => ({ a: 1 }) })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    unmount();

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/c/1/collaboration/documents/7/collaborate");
    expect(config).toMatchObject({ adapter: "fetch", fetchOptions: { keepalive: true } });
    expect(JSON.parse(body as string)).toEqual({
      update: "AQI=",
      state_vector: "Aw==",
      content: { a: 1 },
    });
    expect(calls).toEqual(["destroy"]);
    await Promise.resolve();
    expect(provider.handedOver).toHaveBeenCalled();
  });

  it("hands over as the page is hidden, not only when it unmounts", () => {
    const { result } = renderHook(() =>
      useCollaboration({ socketPath: "documents/7/collaborate", finalContent: () => ({ a: 2 }) })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });

    window.dispatchEvent(new Event("pagehide"));

    expect(calls).toEqual(['send {"a":2}']);
  });

  it("counts a body as synced from its first sync on, through a reconnect", () => {
    const { result } = renderHook(() =>
      useCollaboration({ socketPath: "documents/7/collaborate", finalContent: () => undefined })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    const onSync = provider.on.mock.calls.filter(([type]) => type === "sync").at(-1)?.[1] as (
      synced: boolean
    ) => void;
    expect(result.current.hasSynced).toBe(false);

    act(() => onSync(true));
    expect(result.current).toMatchObject({ isSynced: true, hasSynced: true });

    // The socket dropped and is reconnecting: not in step with the room right
    // now, but the editor already holds the document.
    act(() => onSync(false));
    expect(result.current).toMatchObject({ isSynced: false, hasSynced: true });
  });

  it("starts over when the page moves to another body", () => {
    const { result, rerender } = renderHook(
      ({ path }) => useCollaboration({ socketPath: path, finalContent: () => undefined }),
      { initialProps: { path: "documents/7/collaborate" } }
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    const onSync = provider.on.mock.calls.filter(([type]) => type === "sync").at(-1)?.[1] as (
      synced: boolean
    ) => void;
    act(() => onSync(true));
    expect(result.current.hasSynced).toBe(true);

    rerender({ path: "documents/8/collaborate" });
    expect(result.current.hasSynced).toBe(false);
  });
});
