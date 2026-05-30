import { describe, expect, it } from "vitest";

import { resolveDocumentDownloadUrl, resolveDocumentVersionDownloadUrl } from "./uploadUrl";

// Capacitor.isNativePlatform() is globally mocked to `false` in test setup,
// so these cover the web (same-origin, cookie-auth) path.

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
