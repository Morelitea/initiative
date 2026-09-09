import { render, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { latestSocket, MockWebSocket } from "@/__tests__/helpers/mockWebSocket";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { q } from "@/api/query-keys";
import { AuthContext } from "@/hooks/useAuth";

import { useNotificationStream, useNotificationStreamConnected } from "./useNotificationStream";

// One entry point now, so a batch is one call naming several things. `q` stays
// real — the spec it builds is what these assertions compare against.
const invalidations = vi.hoisted(() => vi.fn());
vi.mock("@/api/query-keys", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/query-keys")>()),
  invalidate: (...specs: unknown[]) => invalidations(...specs),
}));

/** How many batches named this. */
const timesNamed = (spec: unknown) =>
  invalidations.mock.calls.filter((call: unknown[]) =>
    call.some((named) => JSON.stringify(named) === JSON.stringify(spec))
  ).length;

const MSG_AUTH = 5;

const Probe = () => {
  useNotificationStream();
  return null;
};

describe("useNotificationStream", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    invalidations.mockClear();
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("connects to the user-scoped stream, with no guild in the address", () => {
    renderWithProviders(<Probe />);

    expect(latestSocket().url).toContain("/api/v1/notifications/stream");
    expect(latestSocket().url).not.toContain("/g/");
    expect(latestSocket().url.startsWith("ws://") || latestSocket().url.startsWith("wss://")).toBe(
      true
    );
  });

  it("authenticates in the first frame rather than the URL", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();

    expect(socket.url).not.toContain("token");
    expect(socket.sent[0][0]).toBe(MSG_AUTH);
    expect(socket.authPayload()).toEqual({ token: "test-token" });
  });

  it("refetches the inbox when the server says it changed", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    invalidations.mockClear();

    socket.receive({ resource: "notification", action: "created", ids: {} });

    expect(timesNamed(q.notifications())).toBe(1);
  });

  it("catches up on connect, since nothing signalled while the socket was down", () => {
    renderWithProviders(<Probe />);

    latestSocket().open();

    expect(timesNamed(q.notifications())).toBe(1);
  });

  it("re-reads the account when the server says its standing changed", () => {
    const refreshUser = vi.fn();
    renderWithProviders(<Probe />, { auth: { refreshUser } });
    const socket = latestSocket();
    socket.open();
    // The catch-up on connect pokes every channel; this test is about the frame.
    refreshUser.mockClear();
    invalidations.mockClear();

    socket.receive({ resource: "account", action: "membership", ids: {} });

    expect(refreshUser).toHaveBeenCalledTimes(1);
    // Three channels over one socket: none answers for the others.
    expect(timesNamed(q.notifications())).toBe(0);
    expect(timesNamed(q.contactGrants())).toBe(0);
  });

  it("re-reads the contact lists when the server says they moved", () => {
    const refreshUser = vi.fn();
    renderWithProviders(<Probe />, { auth: { refreshUser } });
    const socket = latestSocket();
    socket.open();
    refreshUser.mockClear();
    invalidations.mockClear();

    socket.receive({ resource: "contacts", action: "changed", ids: {} });

    // All three move together: accepting a connection opens a channel, and
    // leaving a community closes one.
    expect(timesNamed(q.contactGrants())).toBe(1);
    expect(timesNamed(q.ignoredAccounts())).toBe(1);
    expect(timesNamed(q.dmSettings())).toBe(1);
    // And neither of the other channels is disturbed.
    expect(refreshUser).not.toHaveBeenCalled();
    expect(timesNamed(q.notifications())).toBe(0);
  });

  it("ignores a frame naming a channel it does not know", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    invalidations.mockClear();

    socket.receive({ resource: "something-new", action: "changed", ids: {} });

    expect(timesNamed(q.notifications())).toBe(0);
    expect(timesNamed(q.contactGrants())).toBe(0);
  });

  it("catches up on both channels after the socket was down", () => {
    const refreshUser = vi.fn();
    renderWithProviders(<Probe />, { auth: { refreshUser } });

    latestSocket().open();

    // Anything that happened while it was down was never signalled, and that
    // includes being added to a community.
    expect(refreshUser).toHaveBeenCalledTimes(1);
    expect(timesNamed(q.notifications())).toBe(1);
    expect(timesNamed(q.contactGrants())).toBe(1);
  });

  it("re-reads everything when the server says its own bus was down", () => {
    const refreshUser = vi.fn();
    renderWithProviders(<Probe />, { auth: { refreshUser } });
    const socket = latestSocket();
    socket.open();
    invalidations.mockClear();
    refreshUser.mockClear();

    // The socket never dropped, so nothing here noticed. The gap was on the
    // server's side of it, and it cannot say what went past — only that
    // something did.
    socket.receive({ resource: "resync", action: "changed", ids: {} });

    expect(timesNamed(q.notifications())).toBe(1);
    expect(timesNamed(q.contactGrants())).toBe(1);
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });

  it("ignores a heartbeat beyond taking it as proof of life", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    invalidations.mockClear();

    socket.receive({ resource: "heartbeat", action: "alive", ids: {} });

    expect(timesNamed(q.notifications())).toBe(0);
  });

  it("closes a socket the server has gone silent on", async () => {
    // A dropped connection does not always close — a suspended laptop, a NAT
    // timeout — and one that reports itself open while delivering nothing
    // would otherwise keep the fallback poll switched off indefinitely.
    vi.useFakeTimers();
    try {
      renderWithProviders(<Probe />);
      const socket = latestSocket();
      socket.open();
      expect(socket.readyState).toBe(MockWebSocket.OPEN);

      // Past the limit, and past the next check after it.
      await vi.advanceTimersByTimeAsync(110_000);

      expect(socket.closed).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a socket the server is still beating on", async () => {
    vi.useFakeTimers();
    try {
      renderWithProviders(<Probe />);
      const socket = latestSocket();
      socket.open();

      for (let elapsed = 0; elapsed < 95_000; elapsed += 30_000) {
        await vi.advanceTimersByTimeAsync(30_000);
        socket.receive({ resource: "heartbeat", action: "alive", ids: {} });
      }

      expect(socket.closed).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("tries the account again when the re-read fails", async () => {
    vi.useFakeTimers();
    try {
      const refreshUser = vi.fn().mockResolvedValue(undefined);
      renderWithProviders(<Probe />, { auth: { refreshUser } });
      const socket = latestSocket();
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
      const socket = latestSocket();
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
      const socket = latestSocket();
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
    const socket = latestSocket();
    socket.open();
    invalidations.mockClear();

    socket.receive({ resource: "task", ids: { task_id: 1 } });
    socket.onmessage?.({ data: "not json" });

    expect(timesNamed(q.notifications())).toBe(0);
  });

  it("stays up across an account re-read rather than rebuilding for it", () => {
    // Connecting asks for a re-read, and a re-read that replaced the socket
    // would connect again — a loop that hammers the API until it rate-limits.
    // The socket belongs to a person, not to a particular reading of them.
    const account = buildUser();
    const authValue = (user: UserRead) =>
      ({
        user,
        token: "test-token",
        loading: false,
        refreshUser: vi.fn(),
      }) as unknown as React.ComponentProps<typeof AuthContext.Provider>["value"];
    const tree = (user: UserRead) => (
      <AuthContext.Provider value={authValue(user)}>
        <Probe />
      </AuthContext.Provider>
    );

    const { rerender } = render(tree(account));
    latestSocket().open();
    expect(MockWebSocket.instances).toHaveLength(1);

    // A fresh object for the same person, which is what every re-read returns.
    rerender(tree({ ...account }));

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(latestSocket().closed).toBe(false);
  });

  it("closes the socket when the hook unmounts", () => {
    const { unmount } = renderWithProviders(<Probe />);
    const socket = latestSocket();
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
      latestSocket().open();
      expect(MockWebSocket.instances).toHaveLength(1);

      latestSocket().serverClose(1006);
      await vi.advanceTimersByTimeAsync(2000);

      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it("gives up after repeated auth rejections instead of hammering the endpoint", async () => {
      renderWithProviders(<Probe />);

      for (let attempt = 0; attempt < 5; attempt += 1) {
        latestSocket().serverClose(1008);
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
    latestSocket().open();
    await waitFor(() => expect(observed.result.current).toBe(true));

    latestSocket().serverClose(1006);
    await waitFor(() => expect(observed.result.current).toBe(false));

    stream.unmount();
    observed.unmount();
  });
});
