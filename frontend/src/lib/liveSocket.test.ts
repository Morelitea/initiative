/**
 * The one socket both push channels share, on its own.
 *
 * What a frame means is the channel's business; that a socket is watched for
 * going quiet is this module's, so it is proved here rather than once per
 * hook above it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { latestSocket, MockWebSocket } from "@/__tests__/helpers/mockWebSocket";

import { openLiveSocket } from "./liveSocket";

const open = () =>
  openLiveSocket({ url: "ws://localhost/stream", auth: () => ({}), onFrame: () => {} });

describe("openLiveSocket — silence", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("closes a socket the server has gone silent on", async () => {
    // A dropped connection does not always close — a suspended laptop, a NAT
    // timeout — and one that reports itself open while delivering nothing
    // would otherwise keep the fallback poll switched off indefinitely.
    const live = open();
    const socket = latestSocket();
    socket.open();
    expect(socket.readyState).toBe(MockWebSocket.OPEN);

    // Past the limit, and past the next check after it.
    await vi.advanceTimersByTimeAsync(110_000);

    expect(socket.closed).toBe(true);
    live.close();
  });

  it("keeps a socket the server is still beating on", async () => {
    const live = open();
    const socket = latestSocket();
    socket.open();

    for (let elapsed = 0; elapsed < 95_000; elapsed += 30_000) {
      await vi.advanceTimersByTimeAsync(30_000);
      socket.receive({ heartbeat: true });
    }

    expect(socket.closed).toBe(false);
    live.close();
  });
});
