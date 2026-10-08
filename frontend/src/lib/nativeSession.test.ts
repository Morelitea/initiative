import { afterEach, describe, expect, it } from "vitest";

import { CREDENTIAL_KEYS, removeItem } from "@/lib/storage";

import { clearRefreshToken, readRefreshToken, storeRefreshToken } from "./nativeSession";

afterEach(() => {
  removeItem(CREDENTIAL_KEYS.refreshToken);
});

describe("the refresh token the native app keeps", () => {
  it("comes back out as it went in", () => {
    storeRefreshToken("rt-1");
    expect(readRefreshToken()).toBe("rt-1");
  });

  it("is gone once cleared", () => {
    storeRefreshToken("rt-1");
    clearRefreshToken();
    expect(readRefreshToken()).toBeNull();
  });

  it("reads as absent before anything is signed in", () => {
    expect(readRefreshToken()).toBeNull();
  });
});
