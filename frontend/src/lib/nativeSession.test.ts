import { afterEach, describe, expect, it } from "vitest";

import { removeItem } from "@/lib/storage";

import {
  clearRefreshToken,
  REFRESH_TOKEN_KEY,
  readRefreshToken,
  sessionFromResponse,
  storeRefreshToken,
} from "./nativeSession";

afterEach(() => {
  removeItem(REFRESH_TOKEN_KEY);
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

describe("reading a session out of a sign-in", () => {
  it("takes the pair when both are there", () => {
    expect(sessionFromResponse({ access_token: "at", refresh_token: "rt" })).toEqual({
      accessToken: "at",
      refreshToken: "rt",
    });
  });

  it("finds none when a deployment answers the old way", () => {
    // A backend that has not been updated hands back the device token alone.
    // That is the previous behaviour, not a failure, so the caller is told
    // there is no session rather than handed half of one.
    expect(sessionFromResponse({})).toBeNull();
    expect(sessionFromResponse({ access_token: "at" })).toBeNull();
    expect(sessionFromResponse({ refresh_token: "rt" })).toBeNull();
  });

  it("finds none when the fields are present but empty", () => {
    expect(sessionFromResponse({ access_token: "", refresh_token: "" })).toBeNull();
  });
});
