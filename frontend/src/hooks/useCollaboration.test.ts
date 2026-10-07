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
  destroy: vi.fn(() => calls.push("destroy")),
};

vi.mock("./useAuth", () => ({ useAuth: () => ({ token: "t", user: { id: 1 } }) }));
vi.mock("./useCommunities", () => ({ useCommunities: () => ({ activeCommunityId: 1 }) }));
vi.mock("@/lib/wsUrl", () => ({
  buildCommunityWsUrl: (_g: number, path: string) => `ws://x/${path}`,
}));
vi.mock("@/lib/yjs/CollaborationProvider", () => ({
  getLiveProvider: () => null,
  getOrCreateProvider: () => provider,
}));

describe("useCollaboration", () => {
  beforeEach(() => {
    calls.length = 0;
    provider.connected = true;
    provider.unsentEdits.mockReturnValue(null);
  });

  it("hands nothing over while the socket is open", () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({});
    const { result, unmount } = renderHook(() =>
      useCollaboration({ socketPath: "files/7/collaborate" })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    unmount();
    expect(post).not.toHaveBeenCalled();
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
      useCollaboration({ socketPath: "files/7/collaborate" })
    );
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    unmount();

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, config] = post.mock.calls[0];
    expect(url).toBe("/c/1/collaboration/files/7/collaborate");
    expect(config).toMatchObject({ adapter: "fetch", fetchOptions: { keepalive: true } });
    expect(JSON.parse(body as string)).toEqual({ update: "AQI=" });
    expect(calls).toEqual(["destroy"]);
    await Promise.resolve();
    expect(provider.handedOver).toHaveBeenCalled();
  });

  it("hands over as the page is hidden, not only when it unmounts", () => {
    provider.connected = false;
    provider.unsentEdits.mockReturnValue({
      update: new Uint8Array([1, 2]),
      stateVector: new Uint8Array([3]),
    });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({});
    const { result } = renderHook(() => useCollaboration({ socketPath: "files/7/collaborate" }));
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });

    window.dispatchEvent(new Event("pagehide"));

    expect(post).toHaveBeenCalledTimes(1);
  });

  it("counts a body as synced from its first sync on, through a reconnect", () => {
    const { result } = renderHook(() => useCollaboration({ socketPath: "files/7/collaborate" }));
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
    const { result, rerender } = renderHook(({ path }) => useCollaboration({ socketPath: path }), {
      initialProps: { path: "files/7/collaborate" },
    });
    act(() => {
      result.current.providerFactory?.("7", new Map());
    });
    const onSync = provider.on.mock.calls.filter(([type]) => type === "sync").at(-1)?.[1] as (
      synced: boolean
    ) => void;
    act(() => onSync(true));
    expect(result.current.hasSynced).toBe(true);

    rerender({ path: "files/8/collaborate" });
    expect(result.current.hasSynced).toBe(false);
  });
});
