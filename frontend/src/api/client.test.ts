import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { clearRefreshToken, REFRESH_TOKEN_KEY, storeRefreshToken } from "@/lib/nativeSession";
import { removeItem } from "@/lib/storage";

import {
  AUTH_FACTOR_REQUIRED_EVENT,
  AUTH_STEP_UP_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  apiClient,
  setAuthToken,
  setHasActiveSession,
} from "./client";

// The silent-renewal interceptor: a 401 gets one POST /auth/refresh and a
// retry before it surfaces as a signed-out state (web only — the refresh
// cookie is HttpOnly, so the tests only observe the requests, not the cookie).
// The native app has no cookie to send: it keeps its own refresh token and
// hands it over, and rotation means the replacement has to be kept too.
describe("renewal for a client that holds its own refresh token", () => {
  afterEach(() => {
    setHasActiveSession(false);
    setAuthToken(null);
    clearRefreshToken();
    removeItem(REFRESH_TOKEN_KEY);
  });

  it("sends the stored token and keeps the one that comes back", async () => {
    storeRefreshToken("rt-old");
    let sent: unknown = null;
    let renewed = false;
    server.use(
      http.get("/api/v1/users/me", () =>
        renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", async ({ request }) => {
        sent = await request.json();
        renewed = true;
        return HttpResponse.json({ access_token: "fresh", refresh_token: "rt-new" });
      })
    );

    await apiClient.get("/users/me");

    expect(sent).toEqual({ refresh_token: "rt-old" });
    // Spent on use, so the one held has to be the replacement.
    const { readRefreshToken } = await import("@/lib/nativeSession");
    expect(readRefreshToken()).toBe("rt-new");
  });

  it("renews on native rather than signing the app out", async () => {
    // Native was excluded from renewal when the only credential it could hold
    // was a device token that never expired — a 401 then really was the end.
    // An app holding a refresh token is in the browser's position, and an
    // expired access token has to renew rather than end the session.
    const { Capacitor } = await import("@capacitor/core");
    const native = vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    storeRefreshToken("rt-native");
    setHasActiveSession(true);
    const signedOut = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, signedOut);

    let renewed = false;
    server.use(
      http.get("/api/v1/users/me", () =>
        renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", () => {
        renewed = true;
        return HttpResponse.json({ access_token: "fresh", refresh_token: "rt-next" });
      })
    );

    const response = await apiClient.get("/users/me");

    expect(response.data).toEqual({ id: 1 });
    expect(signedOut).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, signedOut);
    native.mockRestore();
  });

  it("sends no body when there is nothing stored", async () => {
    let sentBody: string | null = null;
    let renewed = false;
    server.use(
      http.get("/api/v1/users/me", () =>
        renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", async ({ request }) => {
        sentBody = await request.text();
        renewed = true;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    await apiClient.get("/users/me");

    // The browser's token is a cookie it cannot read; it sends nothing and the
    // server reads the jar.
    expect(sentBody).toBe("");
  });
});

describe("silent session renewal", () => {
  afterEach(() => {
    setHasActiveSession(false);
    setAuthToken(null);
  });

  it("renews the session and retries the failed request", async () => {
    let refreshCalls = 0;
    let renewed = false;
    server.use(
      http.get("/api/v1/users/me", () =>
        renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        renewed = true;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    const response = await apiClient.get("/users/me");

    expect(response.data).toEqual({ id: 1 });
    expect(refreshCalls).toBe(1);
  });

  it("shares one renewal across concurrent 401s", async () => {
    let refreshCalls = 0;
    let renewed = false;
    const gated = () =>
      renewed ? HttpResponse.json({ ok: true }) : new HttpResponse(null, { status: 401 });
    server.use(
      http.get("/api/v1/users/me", gated),
      http.get("/api/v1/notifications", gated),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        renewed = true;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    const [a, b] = await Promise.all([apiClient.get("/users/me"), apiClient.get("/notifications")]);

    expect(a.data).toEqual({ ok: true });
    expect(b.data).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
  });

  it("surfaces the signed-out state when renewal fails", async () => {
    let refreshCalls = 0;
    server.use(
      http.get("/api/v1/users/me", () => new HttpResponse(null, { status: 401 })),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return new HttpResponse(null, { status: 401 });
      })
    );
    setHasActiveSession(true);
    const onUnauthorized = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);

    try {
      await expect(apiClient.get("/users/me")).rejects.toMatchObject({
        response: { status: 401 },
      });
      // Exactly one renewal attempt — the refresh endpoint's own 401 must not
      // recurse into another renewal.
      expect(refreshCalls).toBe(1);
      expect(onUnauthorized).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    }
  });

  it("emits one signed-out event when concurrent 401s share a failed renewal", async () => {
    let refreshCalls = 0;
    const rejected = () => new HttpResponse(null, { status: 401 });
    server.use(
      http.get("/api/v1/users/me", rejected),
      http.get("/api/v1/notifications", rejected),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return rejected();
      })
    );
    setHasActiveSession(true);
    const onUnauthorized = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);

    try {
      const results = await Promise.allSettled([
        apiClient.get("/users/me"),
        apiClient.get("/notifications"),
      ]);
      expect(results.map((r) => r.status)).toEqual(["rejected", "rejected"]);
      expect(refreshCalls).toBe(1);
      expect(onUnauthorized).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    }
  });

  // A renewal can fail without saying anything about the session: a restart,
  // a proxy hiccup, a rate limit, a dead network. The session outlives those.
  it.each([
    ["a server error", () => new HttpResponse(null, { status: 503 })],
    ["a rate limit", () => new HttpResponse(null, { status: 429 })],
    ["a request declined before it was handled", () => new HttpResponse(null, { status: 403 })],
    ["nothing answering", () => HttpResponse.error()],
  ])("keeps the session when the renewal fails with %s", async (_label, failure) => {
    server.use(
      http.get("/api/v1/users/me", () => new HttpResponse(null, { status: 401 })),
      http.post("/api/v1/auth/refresh", failure)
    );
    setHasActiveSession(true);
    const onUnauthorized = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);

    try {
      // The request still fails — it just doesn't take the session with it.
      await expect(apiClient.get("/users/me")).rejects.toBeDefined();
      expect(onUnauthorized).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    }
  });

  // The guard above sees only its own window, so renewals are taken in turns
  // through a lock the whole origin shares.
  it("renews under a lock the other windows share", async () => {
    const held: string[] = [];
    let renewedInsideLock = false;
    const request = vi.fn(async (name: string, run: () => Promise<unknown>) => {
      held.push(`held:${name}`);
      const result = await run();
      held.push(`released:${name}`);
      return result;
    });
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });
    let renewed = false;
    server.use(
      http.get("/api/v1/users/me", () =>
        renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", () => {
        renewed = true;
        // The lock is taken before the renewal and not yet let go.
        renewedInsideLock = held.length === 1 && held[0] === "held:initiative:auth:refresh";
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    try {
      const response = await apiClient.get("/users/me");

      expect(response.data).toEqual({ id: 1 });
      expect(request).toHaveBeenCalledTimes(1);
      expect(renewedInsideLock).toBe(true);
      expect(held).toEqual(["held:initiative:auth:refresh", "released:initiative:auth:refresh"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // Older browsers and some embedded views have no lock manager, so the turn
  // is taken through storage the windows share instead.
  describe("without a lock manager", () => {
    const TURN_KEY = "initiative-auth-renewal-turn";
    const DONE_KEY = "initiative-auth-renewal-done";

    beforeEach(() => {
      localStorage.clear();
    });

    /** Claim the turn on behalf of another window, once this one has claimed. */
    const takeTurnAsAnotherWindow = async () => {
      await vi.waitFor(() => expect(localStorage.getItem(TURN_KEY)).not.toBeNull(), {
        interval: 1,
      });
      localStorage.setItem(TURN_KEY, "another-window");
    };

    /** Report back, once the waiting window is listening for it. */
    const reportAsAnotherWindow = (outcome: "ok" | "no") => {
      setTimeout(() => {
        window.dispatchEvent(
          new StorageEvent("storage", { key: DONE_KEY, newValue: `${Date.now()}:${outcome}` })
        );
      }, 120);
    };

    it("renews and says so, for the windows waiting on it", async () => {
      let renewed = false;
      server.use(
        http.get("/api/v1/users/me", () =>
          renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
        ),
        http.post("/api/v1/auth/refresh", () => {
          renewed = true;
          return HttpResponse.json({ access_token: "fresh" });
        })
      );

      await expect(apiClient.get("/users/me")).resolves.toMatchObject({ data: { id: 1 } });
      // The turn is given up, and how it went is left where peers can read it.
      expect(localStorage.getItem(TURN_KEY)).toBeNull();
      expect(localStorage.getItem(DONE_KEY)).toMatch(/:ok$/);
    });

    it("uses what another window renewed rather than renewing again", async () => {
      let refreshCalls = 0;
      let renewed = false;
      server.use(
        http.get("/api/v1/users/me", () =>
          renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
        ),
        http.post("/api/v1/auth/refresh", () => {
          refreshCalls += 1;
          return HttpResponse.json({ access_token: "fresh" });
        })
      );

      const pending = apiClient.get("/users/me");
      // Another window claims the turn after this one — the last write wins —
      // and then reports that it went well, which in a real browser is what
      // the storage event carries.
      await takeTurnAsAnotherWindow();
      renewed = true;
      reportAsAnotherWindow("ok");

      await expect(pending).resolves.toMatchObject({ data: { id: 1 } });
      expect(refreshCalls).toBe(0);
    });

    it("renews itself when the window holding the turn did not get there", async () => {
      let renewed = false;
      server.use(
        http.get("/api/v1/users/me", () =>
          renewed ? HttpResponse.json({ id: 1 }) : new HttpResponse(null, { status: 401 })
        ),
        http.post("/api/v1/auth/refresh", () => {
          renewed = true;
          return HttpResponse.json({ access_token: "fresh" });
        })
      );

      const pending = apiClient.get("/users/me");
      await takeTurnAsAnotherWindow();
      reportAsAnotherWindow("no");

      // It does not take the other window's word for a renewal that failed.
      await expect(pending).resolves.toMatchObject({ data: { id: 1 } });
    });
  });

  it("passes a guild step-up 401 through without renewal or sign-out", async () => {
    let refreshCalls = 0;
    server.use(
      http.get("/api/v1/g/1/projects/", () =>
        HttpResponse.json(
          { detail: "GUILD_AUTH_STEP_UP_REQUIRED" },
          {
            status: 401,
            headers: { "X-Auth-Step-Up": "corp", "X-Auth-Step-Up-Guild": "1" },
          }
        )
      ),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );
    setHasActiveSession(true);
    const onUnauthorized = vi.fn();
    const onStepUp = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    window.addEventListener(AUTH_STEP_UP_EVENT, onStepUp);

    try {
      await expect(apiClient.get("/g/1/projects/")).rejects.toMatchObject({
        response: { status: 401 },
      });
      expect(refreshCalls).toBe(0);
      expect(onUnauthorized).not.toHaveBeenCalled();
      // The challenge is announced (with the provider to step up with and
      // the guild whose login flow serves it) so the global dialog can offer
      // the sign-in.
      expect(onStepUp).toHaveBeenCalledTimes(1);
      expect((onStepUp.mock.calls[0][0] as CustomEvent).detail).toEqual({
        providerSlug: "corp",
        guildId: 1,
      });
    } finally {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
      window.removeEventListener(AUTH_STEP_UP_EVENT, onStepUp);
    }
  });

  it.each([
    ["GUILD_AUTH_FACTOR_REQUIRED", "totp"],
    ["GUILD_AUTH_PASSKEY_REQUIRED", "passkey"],
  ])("announces %s as a challenge naming the factor", async (detail, kind) => {
    let refreshCalls = 0;
    server.use(
      http.get("/api/v1/g/7/projects/", () =>
        HttpResponse.json({ detail }, { status: 401, headers: { "X-Auth-Step-Up-Guild": "7" } })
      ),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );
    setHasActiveSession(true);
    const onUnauthorized = vi.fn();
    const onFactor = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    window.addEventListener(AUTH_FACTOR_REQUIRED_EVENT, onFactor);

    try {
      await expect(apiClient.get("/g/7/projects/")).rejects.toMatchObject({
        response: { status: 401 },
      });
      // Neither renewed nor read as signed out: the session is fine, it is
      // this community that wants more from it.
      expect(refreshCalls).toBe(0);
      expect(onUnauthorized).not.toHaveBeenCalled();
      expect(onFactor).toHaveBeenCalledTimes(1);
      expect((onFactor.mock.calls[0][0] as CustomEvent).detail).toEqual({ guildId: 7, kind });
    } finally {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
      window.removeEventListener(AUTH_FACTOR_REQUIRED_EVENT, onFactor);
      setHasActiveSession(false);
    }
  });

  it("does not renew for auth lifecycle endpoints", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/v1/auth/token", () => new HttpResponse(null, { status: 401 })),
      http.post("/api/v1/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: "fresh" });
      })
    );

    await expect(apiClient.post("/auth/token")).rejects.toMatchObject({
      response: { status: 401 },
    });
    expect(refreshCalls).toBe(0);
  });

  it("rotates an in-memory Bearer token so the retry does not resend the stale one", async () => {
    setAuthToken("stale");
    server.use(
      http.get("/api/v1/users/me", ({ request }) =>
        request.headers.get("Authorization") === "Bearer fresh"
          ? HttpResponse.json({ id: 1 })
          : new HttpResponse(null, { status: 401 })
      ),
      http.post("/api/v1/auth/refresh", () => HttpResponse.json({ access_token: "fresh" }))
    );

    const response = await apiClient.get("/users/me");

    expect(response.data).toEqual({ id: 1 });
  });
});
