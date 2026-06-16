import { Capacitor } from "@capacitor/core";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";

import { apiClient } from "@/api/client";

import { clearUploadToken, getUploadToken, refreshUploadToken } from "./uploadToken";

// The scoped upload token is a NATIVE-only concern: on web, media loads use the
// HttpOnly session cookie, so getUploadToken() must stay a no-op there.

// Re-spy per test: afterEach's restoreAllMocks() detaches the spy, so a
// module-level spy would only intercept the first test's calls.
let postMock: MockInstance;

describe("uploadToken", () => {
  beforeEach(() => {
    clearUploadToken();
    postMock = vi.spyOn(apiClient, "post");
    postMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearUploadToken();
  });

  it("returns null on web without hitting the network", () => {
    // Capacitor.isNativePlatform() is mocked to false globally.
    expect(getUploadToken()).toBeNull();
    expect(postMock).not.toHaveBeenCalled();
  });

  it("refreshUploadToken posts to the mint endpoint and caches the token", async () => {
    postMock.mockResolvedValueOnce({
      data: { upload_token: "scoped-abc", expires_in: 600 },
    });

    const token = await refreshUploadToken();

    expect(token).toBe("scoped-abc");
    expect(postMock).toHaveBeenCalledWith("/auth/upload-token");
  });

  it("getUploadToken serves the cached token on native and refreshes in the background", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    postMock.mockResolvedValue({
      data: { upload_token: "scoped-xyz", expires_in: 600 },
    });

    // First call has no cache yet → returns null but kicks off a refresh.
    expect(getUploadToken()).toBeNull();
    // Let the background refresh resolve.
    await refreshUploadToken();

    expect(getUploadToken()).toBe("scoped-xyz");
  });

  it("concurrent refreshes share a single in-flight request", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    postMock.mockResolvedValue({
      data: { upload_token: "scoped-shared", expires_in: 600 },
    });

    const [a, b] = await Promise.all([refreshUploadToken(), refreshUploadToken()]);

    expect(a).toBe("scoped-shared");
    expect(b).toBe("scoped-shared");
    expect(postMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the previous token when a refresh fails", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    postMock.mockResolvedValueOnce({
      data: { upload_token: "scoped-first", expires_in: 600 },
    });
    await refreshUploadToken();

    postMock.mockRejectedValueOnce(new Error("network"));
    const token = await refreshUploadToken();

    // Transient failure must not blank out a token currently in use.
    expect(token).toBe("scoped-first");
  });

  it("clearUploadToken drops the cached token", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    postMock.mockResolvedValue({
      data: { upload_token: "scoped-clear", expires_in: 600 },
    });
    await refreshUploadToken();
    expect(getUploadToken()).toBe("scoped-clear");

    clearUploadToken();
    // After clearing, the synchronous read is null again (and triggers a new
    // background refresh).
    expect(getUploadToken()).toBeNull();
  });
});

describe("uploadToken logout race", () => {
  it("does not revive the cache when cleared while a refresh is in flight", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    let release: (value: unknown) => void = () => {};
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const postMock = vi.spyOn(apiClient, "post").mockImplementation(async () => {
      await gate;
      return { data: { upload_token: "post-logout", expires_in: 600 } };
    });

    const pending = refreshUploadToken();
    // Logout happens while the mint request is still in flight.
    clearUploadToken();
    release(null);

    expect(await pending).toBeNull();
    // The orphaned response must not have re-entered the cache.
    expect(getUploadToken()).toBeNull();
    expect(postMock).toHaveBeenCalled();
  });
});
