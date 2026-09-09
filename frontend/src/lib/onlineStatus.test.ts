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

/** Let the plugin promises the binding kicked off settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  getStatus.mockReset().mockResolvedValue({ connected: true });
  addListener.mockReset().mockResolvedValue({ remove });
  remove.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  // The manager is a singleton shared by the whole suite; hand it back the way
  // it was found, online and with nobody listening to a mocked plugin.
  onlineManager.setEventListener(() => () => {});
  onlineManager.setOnline(true);
});

describe("bindOnlineManagerToDevice", () => {
  it("leaves the browser's own detection alone off-native", async () => {
    native(false);

    bindOnlineManagerToDevice();
    await settle();

    expect(addListener).not.toHaveBeenCalled();
    expect(getStatus).not.toHaveBeenCalled();
  });

  it("takes the device's first reading rather than assuming online", async () => {
    native(true);
    getStatus.mockResolvedValue({ connected: false });

    bindOnlineManagerToDevice();
    await settle();

    expect(onlineManager.isOnline()).toBe(false);
  });

  it("follows the device as the connection comes and goes", async () => {
    native(true);

    bindOnlineManagerToDevice();
    await settle();
    expect(addListener).toHaveBeenCalledWith("networkStatusChange", expect.any(Function));

    emitStatus(false);
    expect(onlineManager.isOnline()).toBe(false);

    emitStatus(true);
    expect(onlineManager.isOnline()).toBe(true);
  });

  it("does not claim to be offline when the status cannot be read", async () => {
    native(true);
    getStatus.mockRejectedValue(new Error("plugin unavailable"));

    bindOnlineManagerToDevice();
    await settle();

    expect(onlineManager.isOnline()).toBe(true);
  });

  it("survives a listener that could not be registered", async () => {
    native(true);
    addListener.mockRejectedValue(new Error("plugin unavailable"));

    bindOnlineManagerToDevice();
    await settle();

    expect(onlineManager.isOnline()).toBe(true);
  });

  it("removes the listener when the manager swaps it out", async () => {
    native(true);

    bindOnlineManagerToDevice();
    await settle();

    // Replacing the event listener runs the previous one's teardown.
    onlineManager.setEventListener(() => () => {});
    expect(remove).toHaveBeenCalled();
  });
});
