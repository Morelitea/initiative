import { describe, expect, it } from "vitest";

import { buildApiWsUrl, buildCommunityWsUrl } from "@/lib/wsUrl";

describe("WebSocket URLs", () => {
  it("addresses a community's socket under /c/, where the API serves it", () => {
    const url = new URL(buildCommunityWsUrl(4, "files/11/collaborate"));
    expect(url.pathname).toBe("/api/v1/c/4/files/11/collaborate");
  });

  it("speaks ws to an http page", () => {
    expect(new URL(buildApiWsUrl("notifications/stream")).protocol).toBe("ws:");
  });
});
