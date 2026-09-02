import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { useNotificationStream, useNotificationStreamConnected } from "./useNotificationStream";

const invalidateNotifications = vi.fn();
vi.mock("@/api/query-keys", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/query-keys")>()),
  invalidateNotifications: () => invalidateNotifications(),
}));

const MSG_AUTH = 5;

/** Stands in for the browser's WebSocket, with the transitions driven by hand. */
class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  binaryType = "blob";
  sent: Uint8Array[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: Uint8Array) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
    this.onclose?.({ code: 1000 });
  }

  // ── Driving helpers ──
  open() {
    this.onopen?.();
  }

  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  serverClose(code: number) {
    this.onclose?.({ code });
  }

  /** The first frame is `[MSG_AUTH, ...utf8 json]`. */
  authPayload(): unknown {
    return JSON.parse(new TextDecoder().decode(this.sent[0].slice(1)));
  }
}

const Probe = () => {
  useNotificationStream();
  return null;
};

const latest = () => MockWebSocket.instances.at(-1) as MockWebSocket;

describe("useNotificationStream", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    invalidateNotifications.mockClear();
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("connects to the user-scoped stream, with no guild in the address", () => {
    renderWithProviders(<Probe />);

    expect(latest().url).toContain("/api/v1/notifications/stream");
    expect(latest().url).not.toContain("/g/");
    expect(latest().url.startsWith("ws://") || latest().url.startsWith("wss://")).toBe(true);
  });

  it("authenticates in the first frame rather than the URL", () => {
    renderWithProviders(<Probe />);
    const socket = latest();
    socket.open();

    expect(socket.url).not.toContain("token");
    expect(socket.sent[0][0]).toBe(MSG_AUTH);
    expect(socket.authPayload()).toEqual({ token: "test-token" });
  });

  it("refetches the inbox when the server says it changed", () => {
    renderWithProviders(<Probe />);
    const socket = latest();
    socket.open();
    invalidateNotifications.mockClear();

    socket.receive({ resource: "notification", action: "created", ids: {} });

    expect(invalidateNotifications).toHaveBeenCalledTimes(1);
  });

  it("catches up on connect, since nothing signalled while the socket was down", () => {
    renderWithProviders(<Probe />);

    latest().open();

    expect(invalidateNotifications).toHaveBeenCalledTimes(1);
  });

  it("re-reads the account when the server says its standing changed", () => {
    const refreshUser = vi.fn();
    renderWithProviders(<Probe />, { auth: { refreshUser } });
    const socket = latest();
    socket.open();
    // The catch-up on connect pokes both; this test is about the frame.
    refreshUser.mockClear();
    invalidateNotifications.mockClear();

    socket.receive({ resource: "account", action: "membership", ids: {} });

    expect(refreshUser).toHaveBeenCalledTimes(1);
    // Two channels over one socket: neither answers for the other.
    expect(invalidateNotifications).not.toHaveBeenCalled();
  });

  it("catches up on both channels after the socket was down", () => {
    const refreshUser = vi.fn();
    renderWithProviders(<Probe />, { auth: { refreshUser } });

    latest().open();

    // Anything that happened while it was down was never signalled, and that
    // includes being added to a community.
    expect(refreshUser).toHaveBeenCalledTimes(1);
    expect(invalidateNotifications).toHaveBeenCalledTimes(1);
  });

  it("tries the account again when the re-read fails", async () => {
    vi.useFakeTimers();
    try {
      const refreshUser = vi.fn().mockResolvedValue(undefined);
      renderWithProviders(<Probe />, { auth: { refreshUser } });
      const socket = latest();
      socket.open();
      await vi.advanceTimersByTimeAsync(0);
      refreshUser.mockClear();
      // Fail the read this frame triggers, and only that one.
      refreshUser.mockRejectedValueOnce(new Error("offline"));

      socket.receive({ resource: "account", action: "membership", ids: {} });
      await vi.advanceTimersByTimeAsync(0);
      expect(refreshUser).toHaveBeenCalledTimes(1);

      // The frame is the only prompt there is, so a failed read must not be
      // the end of it — there is no poll behind this any more.
      await vi.advanceTimersByTimeAsync(2000);
      expect(refreshUser).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps trying at a slow beat rather than giving up", async () => {
    vi.useFakeTimers();
    try {
      const refreshUser = vi.fn().mockResolvedValue(undefined);
      renderWithProviders(<Probe />, { auth: { refreshUser } });
      const socket = latest();
      socket.open();
      await vi.advanceTimersByTimeAsync(0);
      refreshUser.mockClear();
      // Nothing lands from here on.
      refreshUser.mockRejectedValue(new Error("offline"));

      socket.receive({ resource: "account", action: "membership", ids: {} });
      await vi.advanceTimersByTimeAsync(100_000);
      // The read, then the ramp: 2s, 8s, 30s, 60s.
      expect(refreshUser).toHaveBeenCalledTimes(5);

      // Still going, and now at the slow beat — the account is known to be
      // wrong and nothing else is coming to fix it.
      await vi.advanceTimersByTimeAsync(300_000);
      expect(refreshUser).toHaveBeenCalledTimes(6);
      await vi.advanceTimersByTimeAsync(300_000);
      expect(refreshUser).toHaveBeenCalledTimes(7);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops retrying once the hook unmounts", async () => {
    vi.useFakeTimers();
    try {
      const refreshUser = vi.fn().mockResolvedValue(undefined);
      const { unmount } = renderWithProviders(<Probe />, { auth: { refreshUser } });
      const socket = latest();
      socket.open();
      await vi.advanceTimersByTimeAsync(0);
      refreshUser.mockClear();
      refreshUser.mockRejectedValue(new Error("offline"));

      socket.receive({ resource: "account", action: "membership", ids: {} });
      await vi.advanceTimersByTimeAsync(0);
      unmount();
      refreshUser.mockClear();

      await vi.advanceTimersByTimeAsync(600_000);

      expect(refreshUser).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores frames for other resources and malformed ones", () => {
    renderWithProviders(<Probe />);
    const socket = latest();
    socket.open();
    invalidateNotifications.mockClear();

    socket.receive({ resource: "task", ids: { task_id: 1 } });
    socket.onmessage?.({ data: "not json" });

    expect(invalidateNotifications).not.toHaveBeenCalled();
  });

  it("closes the socket when the hook unmounts", () => {
    const { unmount } = renderWithProviders(<Probe />);
    const socket = latest();
    socket.open();

    unmount();

    expect(socket.closed).toBe(true);
  });

  describe("with fake timers", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("reconnects after the connection drops", async () => {
      renderWithProviders(<Probe />);
      latest().open();
      expect(MockWebSocket.instances).toHaveLength(1);

      latest().serverClose(1006);
      await vi.advanceTimersByTimeAsync(2000);

      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it("gives up after repeated auth rejections instead of hammering the endpoint", async () => {
      renderWithProviders(<Probe />);

      for (let attempt = 0; attempt < 5; attempt += 1) {
        latest().serverClose(1008);
        await vi.advanceTimersByTimeAsync(60_000);
      }

      // The initial socket plus two retries, then it stops.
      expect(MockWebSocket.instances).toHaveLength(3);
    });
  });
});

describe("useNotificationStreamConnected", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports the socket state to consumers outside the hook's own tree", async () => {
    const observed = renderHook(() => useNotificationStreamConnected());
    expect(observed.result.current).toBe(false);

    const stream = renderWithProviders(<Probe />);
    latest().open();
    await waitFor(() => expect(observed.result.current).toBe(true));

    latest().serverClose(1006);
    await waitFor(() => expect(observed.result.current).toBe(false));

    stream.unmount();
    observed.unmount();
  });
});
