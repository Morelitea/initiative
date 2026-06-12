import { Capacitor } from "@capacitor/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";

import { getUploadToken } from "./uploadToken";
import {
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
  it("builds the version download path", () => {
    expect(resolveDocumentVersionDownloadUrl(5, 3)).toBe("/api/v1/documents/5/versions/3/download");
  });

  it("appends inline=1 when requested", () => {
    expect(resolveDocumentVersionDownloadUrl(5, 3, true)).toBe(
      "/api/v1/documents/5/versions/3/download?inline=1"
    );
  });

  it("returns null when ids are missing", () => {
    expect(resolveDocumentVersionDownloadUrl(0, 3)).toBeNull();
    expect(resolveDocumentVersionDownloadUrl(5, 0)).toBeNull();
  });

  it("differs from the current-document download path", () => {
    expect(resolveDocumentVersionDownloadUrl(5, 3)).not.toBe(resolveDocumentDownloadUrl(5));
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
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue(
      "http://10.0.2.2:8000/api/v1"
    );
    getUploadTokenMock.mockReturnValue("scoped-upload-token");

    const url = resolveUploadUrl("/uploads/avatars/abc.png");

    expect(url).toBe("http://10.0.2.2:8000/uploads/avatars/abc.png?token=scoped-upload-token");
    expect(getUploadTokenMock).toHaveBeenCalled();
  });

  it("omits the token when none is available yet", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue(
      "http://10.0.2.2:8000/api/v1"
    );
    getUploadTokenMock.mockReturnValue(null);

    expect(resolveUploadUrl("/uploads/avatars/abc.png")).toBe(
      "http://10.0.2.2:8000/uploads/avatars/abc.png"
    );
  });
});
