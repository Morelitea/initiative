import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";

import {
  AUTH_STEP_UP_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  apiClient,
  setAuthToken,
  setHasActiveSession,
} from "./client";

// The silent-renewal interceptor: a 401 gets one POST /auth/refresh and a
// retry before it surfaces as a signed-out state (web only — the refresh
// cookie is HttpOnly, so the tests only observe the requests, not the cookie).
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

  it("passes a guild step-up 401 through without renewal or sign-out", async () => {
    let refreshCalls = 0;
    server.use(
      http.get("/api/v1/g/1/projects/", () =>
        HttpResponse.json(
          { detail: "GUILD_AUTH_STEP_UP_REQUIRED" },
          { status: 401, headers: { "X-Auth-Step-Up": "corp" } }
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
      // The challenge is announced (with the provider to step up with) so the
      // global dialog can offer the sign-in.
      expect(onStepUp).toHaveBeenCalledTimes(1);
      expect((onStepUp.mock.calls[0][0] as CustomEvent).detail).toEqual({
        providerSlug: "corp",
      });
    } finally {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
      window.removeEventListener(AUTH_STEP_UP_EVENT, onStepUp);
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
