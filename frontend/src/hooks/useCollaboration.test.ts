import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCollaboration } from "./useCollaboration";

const calls: string[] = [];
const provider = {
  doc: {},
  on: vi.fn(),
  onCollaborators: vi.fn(),
  onError: vi.fn(),
  connect: vi.fn(),
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
});
