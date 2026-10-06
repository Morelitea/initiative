import { Capacitor } from "@capacitor/core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const issueUploadToken = vi.fn();
vi.mock("@/api/generated/auth/auth", () => ({
  issueUploadToken: () => issueUploadToken(),
}));

import { clearUploadToken, getUploadToken, refreshUploadToken } from "./uploadToken";

// The scoped upload token is a NATIVE-only concern: on web, media loads use the
// HttpOnly session cookie, so getUploadToken() must stay a no-op there.

describe("uploadToken", () => {
  beforeEach(() => {
    clearUploadToken();
    issueUploadToken.mockReset();
  });

  afterEach(() => {
    clearUploadToken();
  });

  it("returns null on web without hitting the network", () => {
    // Capacitor.isNativePlatform() is mocked to false globally.
    expect(getUploadToken()).toBeNull();
    expect(issueUploadToken).not.toHaveBeenCalled();
  });

  it("refreshUploadToken posts to the mint endpoint and caches the token", async () => {
    issueUploadToken.mockResolvedValueOnce({ upload_token: "scoped-abc", expires_in: 600 });

    const token = await refreshUploadToken();

    expect(token).toBe("scoped-abc");
    expect(issueUploadToken).toHaveBeenCalled();
  });

  it("getUploadToken serves the cached token on native and refreshes in the background", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    issueUploadToken.mockResolvedValue({ upload_token: "scoped-xyz", expires_in: 600 });

    // First call has no cache yet → returns null but kicks off a refresh.
    expect(getUploadToken()).toBeNull();
    // Let the background refresh resolve.
    await refreshUploadToken();

    expect(getUploadToken()).toBe("scoped-xyz");
  });

  it("concurrent refreshes share a single in-flight request", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    issueUploadToken.mockResolvedValue({ upload_token: "scoped-shared", expires_in: 600 });

    const [a, b] = await Promise.all([refreshUploadToken(), refreshUploadToken()]);

    expect(a).toBe("scoped-shared");
    expect(b).toBe("scoped-shared");
    expect(issueUploadToken).toHaveBeenCalledTimes(1);
  });

  it("keeps the previous token when a refresh fails", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    issueUploadToken.mockResolvedValueOnce({ upload_token: "scoped-first", expires_in: 600 });
    await refreshUploadToken();

    issueUploadToken.mockRejectedValueOnce(new Error("network"));
    const token = await refreshUploadToken();

    // Transient failure must not blank out a token currently in use.
    expect(token).toBe("scoped-first");
  });

  it("clearUploadToken drops the cached token", async () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    issueUploadToken.mockResolvedValue({ upload_token: "scoped-clear", expires_in: 600 });
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
    issueUploadToken.mockImplementation(async () => {
      await gate;
      return { upload_token: "post-logout", expires_in: 600 };
    });

    const pending = refreshUploadToken();
    // Logout happens while the mint request is still in flight.
    clearUploadToken();
    release(null);

    expect(await pending).toBeNull();
    // The orphaned response must not have re-entered the cache.
    expect(getUploadToken()).toBeNull();
    expect(issueUploadToken).toHaveBeenCalled();
  });
});
