import { Capacitor } from "@capacitor/core";
import { onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { bindOnlineManagerToDevice } from "./onlineStatus";

const getStatus = vi.fn();
const addListener = vi.fn();
const remove = vi.fn();

vi.mock("@capacitor/network", () => ({
  Network: {
    getStatus: () => getStatus(),
    addListener: (event: string, handler: (status: { connected: boolean }) => void) =>
      addListener(event, handler),
  },
}));

/** The handler the plugin was given, so a test can push a change through it. */
const emitStatus = (connected: boolean) => {
  const [, handler] = addListener.mock.calls[0] as [
    string,
    (status: { connected: boolean }) => void,
  ];
  handler({ connected });
};

const native = (value: boolean) => vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(value);

/** Let the promises the binding kicked off settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  getStatus.mockReset().mockResolvedValue({ connected: true });
  addListener.mockReset().mockResolvedValue({ remove });
  remove.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  // The manager is a singleton shared by the whole suite; hand it back the way
  // it was found, online and with nobody listening to a mocked plugin.
  onlineManager.setEventListener(() => () => {});
  onlineManager.setOnline(true);
});

describe("bindOnlineManagerToDevice", () => {
  it("leaves the browser's own detection alone off-native", async () => {
    native(false);

    await bindOnlineManagerToDevice();

    expect(addListener).not.toHaveBeenCalled();
    expect(getStatus).not.toHaveBeenCalled();
  });

  it("takes the device's first reading rather than assuming online", async () => {
    native(true);
    getStatus.mockResolvedValue({ connected: false });

    await bindOnlineManagerToDevice();

    expect(onlineManager.isOnline()).toBe(false);
  });

  it("follows the device as the connection comes and goes", async () => {
    native(true);

    await bindOnlineManagerToDevice();
    expect(addListener).toHaveBeenCalledWith("networkStatusChange", expect.any(Function));

    emitStatus(false);
    expect(onlineManager.isOnline()).toBe(false);

    emitStatus(true);
    expect(onlineManager.isOnline()).toBe(true);
  });

  it("does not start listening until the first reading is in", async () => {
    native(true);
    // The device takes its time answering.
    let resolveStatus: (value: { connected: boolean }) => void = () => {};
    getStatus.mockReturnValue(
      new Promise<{ connected: boolean }>((resolve) => {
        resolveStatus = resolve;
      })
    );

    const binding = bindOnlineManagerToDevice();
    await settle();

    // The ordering is the whole guarantee: while the first reading is still in
    // flight there is no listener, so a change cannot arrive and then be
    // overwritten by the older snapshot landing after it.
    expect(addListener).not.toHaveBeenCalled();

    resolveStatus({ connected: false });
    await binding;

    expect(addListener).toHaveBeenCalled();
    expect(onlineManager.isOnline()).toBe(false);
  });

  it("lets a later change override the first reading", async () => {
    native(true);
    getStatus.mockResolvedValue({ connected: true });

    await bindOnlineManagerToDevice();
    emitStatus(false);

    expect(onlineManager.isOnline()).toBe(false);
  });

  it("gives up on a device that will not answer rather than holding up boot", async () => {
    vi.useFakeTimers();
    native(true);
    getStatus.mockReturnValue(new Promise(() => {}));

    const binding = bindOnlineManagerToDevice();
    await vi.advanceTimersByTimeAsync(2_000);
    await binding;

    // No answer is not evidence of being offline; the listener still stands.
    expect(onlineManager.isOnline()).toBe(true);
    expect(addListener).toHaveBeenCalled();
  });

  it("does not claim to be offline when the status cannot be read", async () => {
    native(true);
    getStatus.mockRejectedValue(new Error("plugin unavailable"));

    await bindOnlineManagerToDevice();

    expect(onlineManager.isOnline()).toBe(true);
  });

  it("falls back to the browser's events when the listener cannot be registered", async () => {
    native(true);
    addListener.mockRejectedValue(new Error("plugin unavailable"));

    await bindOnlineManagerToDevice();
    await settle();

    // Installing a listener took React Query's own off, so something has to
    // report a change — otherwise the app is stuck until it restarts.
    window.dispatchEvent(new Event("offline"));
    expect(onlineManager.isOnline()).toBe(false);

    window.dispatchEvent(new Event("online"));
    expect(onlineManager.isOnline()).toBe(true);
  });

  it("removes the listener when the manager swaps it out", async () => {
    native(true);

    await bindOnlineManagerToDevice();
    await settle();

    // Replacing the event listener runs the previous one's teardown.
    onlineManager.setEventListener(() => () => {});
    expect(remove).toHaveBeenCalled();
  });

  it("stops listening to the browser fallback on teardown too", async () => {
    native(true);
    addListener.mockRejectedValue(new Error("plugin unavailable"));

    await bindOnlineManagerToDevice();
    await settle();
    onlineManager.setEventListener(() => () => {});
    onlineManager.setOnline(true);

    window.dispatchEvent(new Event("offline"));

    expect(onlineManager.isOnline()).toBe(true);
  });
});
