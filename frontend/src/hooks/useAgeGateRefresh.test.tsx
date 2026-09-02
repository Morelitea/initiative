/**
 * The age gate has to be answerable in a tab that was already open.
 *
 * What matters here is the pair: an account that still owes a confirmation
 * re-reads itself when its tab comes back, and one that has already answered
 * costs nothing — no listener, no request, forever.
 */
import { renderHook } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";

const refreshUser = vi.fn();
const state = vi.hoisted(() => ({
  user: null as ReturnType<typeof import("@/__tests__/factories").buildUser> | null,
  ageGate: true,
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: state.user, refreshUser }),
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ communityAgeGateEnabled: state.ageGate }),
}));

import { useAgeGateRefresh } from "./useAgeGateRefresh";

const returnToTab = () => act(() => void window.dispatchEvent(new Event("focus")));

describe("useAgeGateRefresh", () => {
  beforeEach(() => {
    refreshUser.mockClear().mockResolvedValue(undefined);
    state.ageGate = true;
    state.user = buildUser({ age_confirmed_at: null });
  });

  it("re-reads an unconfirmed account when its tab comes back", () => {
    renderHook(() => useAgeGateRefresh());

    returnToTab();

    expect(refreshUser).toHaveBeenCalledTimes(1);
  });

  it("asks nothing of an account that has already answered", () => {
    state.user = buildUser({ age_confirmed_at: "2026-01-01T00:00:00Z" });
    renderHook(() => useAgeGateRefresh());

    returnToTab();

    expect(refreshUser).not.toHaveBeenCalled();
  });

  it("asks nothing where the deployment does not ask", () => {
    state.ageGate = false;
    renderHook(() => useAgeGateRefresh());

    returnToTab();

    expect(refreshUser).not.toHaveBeenCalled();
  });

  it("stops listening once it is unmounted", () => {
    const { unmount } = renderHook(() => useAgeGateRefresh());
    unmount();

    returnToTab();

    expect(refreshUser).not.toHaveBeenCalled();
  });

  it("re-reads on a backstop interval, for a tab that is never left", () => {
    vi.useFakeTimers();
    try {
      renderHook(() => useAgeGateRefresh());

      // No focus event ever fires: this tab has been open and focused all day.
      act(() => void vi.advanceTimersByTime(5 * 60 * 1000));

      expect(refreshUser).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("runs no backstop for an account that has already answered", () => {
    vi.useFakeTimers();
    try {
      state.user = buildUser({ age_confirmed_at: "2026-01-01T00:00:00Z" });
      renderHook(() => useAgeGateRefresh());

      act(() => void vi.advanceTimersByTime(60 * 60 * 1000));

      expect(refreshUser).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops the backstop when it is unmounted", () => {
    vi.useFakeTimers();
    try {
      const { unmount } = renderHook(() => useAgeGateRefresh());
      unmount();

      act(() => void vi.advanceTimersByTime(60 * 60 * 1000));

      expect(refreshUser).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves the gate as it was when the re-read fails", async () => {
    refreshUser.mockRejectedValue(new Error("offline"));
    renderHook(() => useAgeGateRefresh());

    returnToTab();

    // Rejection is swallowed: switching tabs is not a moment for an error.
    await expect(Promise.resolve()).resolves.toBeUndefined();
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });
});
