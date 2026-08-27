import { Capacitor } from "@capacitor/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";

import { getUploadToken } from "./uploadToken";
import {
  resolveArtworkUrl,
  resolveDocumentDownloadUrl,
  resolveDocumentVersionDownloadUrl,
  resolveUploadUrl,
} from "./uploadUrl";

// Mock the scoped-token module so we can assert uploadUrl stamps the SHORT-LIVED
// upload token (never the long-lived session JWT) into native media URLs.
vi.mock("./uploadToken", () => ({
  getUploadToken: vi.fn(() => null),
}));

const getUploadTokenMock = vi.mocked(getUploadToken);

// Capacitor.isNativePlatform() is globally mocked to `false` in test setup,
// so the default-path tests cover the web (same-origin, cookie-auth) flow.

describe("resolveDocumentVersionDownloadUrl", () => {
  it("builds the guild-scoped version download path", () => {
    expect(resolveDocumentVersionDownloadUrl(5, 3, 7)).toBe(
      "/api/v1/g/7/documents/5/versions/3/download"
    );
  });

  it("appends inline=1 when requested", () => {
    expect(resolveDocumentVersionDownloadUrl(5, 3, 7, true)).toBe(
      "/api/v1/g/7/documents/5/versions/3/download?inline=1"
    );
  });

  it("returns null when ids are missing", () => {
    expect(resolveDocumentVersionDownloadUrl(0, 3, 7)).toBeNull();
    expect(resolveDocumentVersionDownloadUrl(5, 0, 7)).toBeNull();
    expect(resolveDocumentVersionDownloadUrl(5, 3, 0)).toBeNull();
  });

  it("differs from the current-document download path", () => {
    expect(resolveDocumentVersionDownloadUrl(5, 3, 7)).not.toBe(resolveDocumentDownloadUrl(5, 7));
  });
});

describe("resolveUploadUrl (web)", () => {
  it("returns same-origin /uploads/ path unchanged with no token query param", () => {
    // Web flow: HttpOnly cookie authenticates the <img> load — no ?token=.
    expect(resolveUploadUrl("/uploads/avatars/abc.png")).toBe("/uploads/avatars/abc.png");
  });

  it("passes through data URIs untouched", () => {
    expect(resolveUploadUrl("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA");
  });
});

describe("resolveUploadUrl (native)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getUploadTokenMock.mockReset();
    getUploadTokenMock.mockReturnValue(null);
  });

  it("stamps the SHORT-LIVED scoped upload token (not the session JWT) into the URL", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");
    getUploadTokenMock.mockReturnValue("scoped-upload-token");

    const url = resolveUploadUrl("/uploads/avatars/abc.png");

    expect(url).toBe("http://10.0.2.2:8000/uploads/avatars/abc.png?token=scoped-upload-token");
    expect(getUploadTokenMock).toHaveBeenCalled();
  });

  it("omits the token when none is available yet", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");
    getUploadTokenMock.mockReturnValue(null);

    expect(resolveUploadUrl("/uploads/avatars/abc.png")).toBe(
      "http://10.0.2.2:8000/uploads/avatars/abc.png"
    );
  });
});

describe("resolveArtworkUrl", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("leaves catalog artwork paths alone on web", () => {
    expect(resolveArtworkUrl("/marketplace/core-guild-calendar.svg")).toBe(
      "/marketplace/core-guild-calendar.svg"
    );
    expect(resolveArtworkUrl("/api/v1/marketplace/media/abc123")).toBe(
      "/api/v1/marketplace/media/abc123"
    );
  });

  it("keeps bundled artwork bundle-relative on native", () => {
    // Shipped with the web bundle: the native app already holds the file, so
    // sending the request to the API origin would be a needless round trip.
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");

    expect(resolveArtworkUrl("/marketplace/core-guild-calendar.svg")).toBe(
      "/marketplace/core-guild-calendar.svg"
    );
    expect(resolveArtworkUrl("/icons/logo.svg")).toBe("/icons/logo.svg");
  });

  it("addresses mirrored registry artwork at the API origin on native", () => {
    // Served only by the API: bundle-relative it resolves inside the app's own
    // origin and the image breaks.
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");

    expect(resolveArtworkUrl("/api/v1/marketplace/media/abc123")).toBe(
      "http://10.0.2.2:8000/api/v1/marketplace/media/abc123"
    );
  });

  it("adds no token — the media route is public", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue("http://10.0.2.2:8000/api/v1");
    getUploadTokenMock.mockReturnValue("scoped-upload-token");

    expect(resolveArtworkUrl("/api/v1/marketplace/media/abc123")).not.toContain("token=");
  });

  it("passes absolute URLs and data URIs through, and null for nothing", () => {
    expect(resolveArtworkUrl("https://cdn.example.test/icon.svg")).toBe(
      "https://cdn.example.test/icon.svg"
    );
    expect(resolveArtworkUrl("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA");
    expect(resolveArtworkUrl(null)).toBeNull();
    expect(resolveArtworkUrl(undefined)).toBeNull();
    expect(resolveArtworkUrl("")).toBeNull();
  });
});
