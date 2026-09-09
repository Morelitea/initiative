import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { setItem } from "@/lib/storage";

import { OFFLINE_CACHE_MAX_AGE_MS } from "./offlineCache";
import {
  clearOfflineSession,
  isNoAnswerError,
  isSessionRejected,
  readOfflineGuilds,
  readOfflineSession,
  saveOfflineGuilds,
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
    setItem("initiative-offline-session", "{not json");
    expect(readOfflineSession(SERVER)).toBeNull();
    setItem("initiative-offline-session", JSON.stringify({ savedAt: Date.now() }));
    expect(readOfflineSession(SERVER)).toBeNull();
  });

  it("is gone after it is cleared", () => {
    saveOfflineSession(buildUser(), SERVER);
    clearOfflineSession();
    expect(readOfflineSession(SERVER)).toBeNull();
  });
});

describe("the remembered community list", () => {
  it("hands back what was saved", () => {
    saveOfflineGuilds([{ id: 3, name: "Beyonders" }], SERVER);
    expect(readOfflineGuilds<{ id: number }>(SERVER)).toEqual([{ id: 3, name: "Beyonders" }]);
  });

  it("is refused for a different server", () => {
    saveOfflineGuilds([{ id: 3 }], SERVER);
    expect(readOfflineGuilds("https://other.example")).toBeNull();
  });

  it("expires on the same clock as everything else", () => {
    vi.useFakeTimers();
    saveOfflineGuilds([{ id: 3 }], SERVER);
    vi.advanceTimersByTime(OFFLINE_CACHE_MAX_AGE_MS + 1000);
    expect(readOfflineGuilds(SERVER)).toBeNull();
  });

  it("goes when the session it belongs to goes", () => {
    saveOfflineGuilds([{ id: 3 }], SERVER);
    clearOfflineSession();
    expect(readOfflineGuilds(SERVER)).toBeNull();
  });

  it("discards a list it cannot make sense of", () => {
    setItem("initiative-offline-guilds", "{not json");
    expect(readOfflineGuilds(SERVER)).toBeNull();
  });
});

describe("isSessionRejected", () => {
  it("is true only for a 401 — the server declining the credentials", () => {
    expect(isSessionRejected({ response: { status: 401 } })).toBe(true);
  });

  it("is false for a server having trouble", () => {
    expect(isSessionRejected({ response: { status: 500 } })).toBe(false);
    expect(isSessionRejected({ response: { status: 502 } })).toBe(false);
    expect(isSessionRejected({ response: { status: 503 } })).toBe(false);
  });

  it("is true when the account itself is over", () => {
    // Both come back from the current-user dependency as codes, not prose.
    expect(
      isSessionRejected({ response: { status: 400, data: { detail: "INACTIVE_USER" } } })
    ).toBe(true);
    expect(
      isSessionRejected({ response: { status: 404, data: { detail: "USER_NOT_FOUND" } } })
    ).toBe(true);
  });

  it("is false for a refusal that is about the request, not the session", () => {
    expect(isSessionRejected({ response: { status: 403 } })).toBe(false);
    // A bare 400 or 404 is too broad to read as the account being over — the
    // code is what says so.
    expect(isSessionRejected({ response: { status: 404 } })).toBe(false);
    expect(isSessionRejected({ response: { status: 400 } })).toBe(false);
    expect(
      isSessionRejected({ response: { status: 400, data: { detail: "SOMETHING_ELSE" } } })
    ).toBe(false);
  });

  it("is false when nothing answered at all", () => {
    expect(isSessionRejected({ request: {} })).toBe(false);
    expect(isSessionRejected(null)).toBe(false);
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
