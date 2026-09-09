import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";

import { OFFLINE_CACHE_MAX_AGE_MS } from "./offlineCache";
import {
  clearOfflineSession,
  isNoAnswerError,
  readOfflineSession,
  saveOfflineSession,
} from "./offlineSession";

const SERVER = "https://initiative.example";

beforeEach(() => {
  clearOfflineSession();
});

afterEach(() => {
  vi.useRealTimers();
  clearOfflineSession();
});

describe("the session snapshot", () => {
  it("hands back the user it was saved with", () => {
    const user = buildUser({ full_name: "Alice" });
    saveOfflineSession(user, SERVER);
    expect(readOfflineSession(SERVER)?.id).toBe(user.id);
  });

  it("is nothing at all when none was saved", () => {
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("is refused for a different server, and taken away with it", () => {
    saveOfflineSession(buildUser(), SERVER);
    expect(readOfflineSession("https://other.example")).toBeNull();
    // Cleared, so switching back does not resurrect it.
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("expires on the same clock as the cache it accompanies", () => {
    vi.useFakeTimers();
    saveOfflineSession(buildUser(), SERVER);
    vi.advanceTimersByTime(OFFLINE_CACHE_MAX_AGE_MS - 1000);
    expect(readOfflineSession(SERVER)).not.toBeNull();
    vi.advanceTimersByTime(2000);
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("discards a snapshot it cannot make sense of", () => {
    localStorage.setItem("initiative-offline-session", "{not json");
    expect(readOfflineSession(SERVER)).toBeNull();
    localStorage.setItem("initiative-offline-session", JSON.stringify({ savedAt: Date.now() }));
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("is gone after it is cleared", () => {
    saveOfflineSession(buildUser(), SERVER);
    clearOfflineSession();
    expect(readOfflineSession(SERVER)).toBeNull();
  });
});

describe("isNoAnswerError", () => {
  it("is true when a request was sent and nothing came back", () => {
    expect(isNoAnswerError({ request: {}, message: "Network Error" })).toBe(true);
  });

  it("is true for a timeout", () => {
    expect(isNoAnswerError({ code: "ECONNABORTED", message: "timeout" })).toBe(true);
  });

  it("is false whenever the server answered — a 401 is the server speaking", () => {
    expect(isNoAnswerError({ request: {}, response: { status: 401 } })).toBe(false);
    expect(isNoAnswerError({ request: {}, response: { status: 403 } })).toBe(false);
    expect(isNoAnswerError({ request: {}, response: { status: 500 } })).toBe(false);
  });

  it("is false for anything that is not a request failure at all", () => {
    expect(isNoAnswerError(new Error("boom"))).toBe(false);
    expect(isNoAnswerError(null)).toBe(false);
    expect(isNoAnswerError("nope")).toBe(false);
  });
});
