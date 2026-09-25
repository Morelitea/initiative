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

describe("openLiveSocket — frames and resuming", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("hands a binary frame to onBytes and a JSON one to onFrame", () => {
    const bytes: Uint8Array[] = [];
    const frames: unknown[] = [];
    const live = openLiveSocket({
      url: "ws://localhost/room",
      auth: () => ({}),
      onFrame: (frame) => frames.push(frame),
      onBytes: (data) => bytes.push(data),
    });
    const socket = latestSocket();
    socket.open();

    const payload = new Uint8Array([2, 7, 9]);
    (socket.onmessage as unknown as (event: { data: ArrayBuffer }) => void)({
      data: payload.buffer,
    });
    socket.receive({ heartbeat: true });

    expect(bytes.map((b) => Array.from(b))).toEqual([[2, 7, 9]]);
    expect(frames).toEqual([{ heartbeat: true }]);
    live.close();
  });

  it("tries again at once when the network comes back", () => {
    const live = open();
    const first = latestSocket();
    first.open();
    first.serverClose(1006);

    window.dispatchEvent(new Event("online"));

    expect(latestSocket()).not.toBe(first);
    live.close();
  });

  it("leaves an open socket alone when asked to resume", () => {
    const live = open();
    const socket = latestSocket();
    socket.open();

    live.resume();

    expect(MockWebSocket.instances).toHaveLength(1);
    live.close();
  });

  it("stops listening for the network once closed", () => {
    const live = open();
    latestSocket().open();
    live.close();

    window.dispatchEvent(new Event("online"));

    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
