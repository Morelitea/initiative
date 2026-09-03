/**
 * The two questions this hook file asks about a browser's device.
 *
 * *Is there one* is asked app-wide, so mail is collected wherever you are.
 * *Make sure there is one* is asked by My Messages. They have different
 * answers, and the app asks the first one first — so what matters is that one
 * cannot decide the other, and that registering turns collection on without
 * waiting for a reload.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTestQueryClient } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  ensureDevice: vi.fn(),
  registeredDevice: vi.fn(),
  collect: vi.fn(),
}));

vi.mock("@/crypto/messaging", () => ({
  ensureDevice: () => mocks.ensureDevice(),
  registeredDevice: () => mocks.registeredDevice(),
  collect: () => mocks.collect(),
  markRead: vi.fn(),
  unreadIn: vi.fn(),
  sendText: vi.fn(),
  messageLog: { get: vi.fn() },
}));

import { useCollectMessagesWhereRegistered, useDmDevice } from "./useMyMessages";

const wrapper = (client = createTestQueryClient()) => {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.collect.mockResolvedValue([]);
  mocks.ensureDevice.mockResolvedValue("device-1");
});

describe("this browser's device", () => {
  it("registers one even though the app already asked whether there was one", async () => {
    // A browser that has never opened Messages. Both hooks under one cache, in
    // the order the app mounts them.
    mocks.registeredDevice.mockResolvedValue(undefined);
    const Wrapper = wrapper();

    const { result } = renderHook(
      () => {
        useCollectMessagesWhereRegistered();
        return useDmDevice();
      },
      { wrapper: Wrapper }
    );

    await waitFor(() => expect(result.current.data).toBe("device-1"));
    expect(mocks.ensureDevice).toHaveBeenCalled();
  });

  it("starts collecting as soon as one is registered", async () => {
    mocks.registeredDevice.mockResolvedValue(undefined);
    const Wrapper = wrapper();

    renderHook(
      () => {
        useCollectMessagesWhereRegistered();
        useDmDevice();
      },
      { wrapper: Wrapper }
    );

    await waitFor(() => expect(mocks.collect).toHaveBeenCalled());
  });

  it("collects on a browser that was already set up, without registering", async () => {
    mocks.registeredDevice.mockResolvedValue("device-1");
    const Wrapper = wrapper();

    renderHook(() => useCollectMessagesWhereRegistered(), { wrapper: Wrapper });

    await waitFor(() => expect(mocks.collect).toHaveBeenCalled());
    expect(mocks.ensureDevice).not.toHaveBeenCalled();
  });

  it("collects nothing on a browser that has never been set up", async () => {
    mocks.registeredDevice.mockResolvedValue(undefined);
    const Wrapper = wrapper();

    renderHook(() => useCollectMessagesWhereRegistered(), { wrapper: Wrapper });

    await waitFor(() => expect(mocks.registeredDevice).toHaveBeenCalled());
    expect(mocks.collect).not.toHaveBeenCalled();
  });
});
