import { describe, expect, it } from "vitest";

import { exportFilenameStem, filenameFromDisposition } from "./exportDownload";

describe("exportFilenameStem", () => {
  it("slugifies the resource name and appends the date", () => {
    const stem = exportFilenameStem("Battle Order: Round 2!", "queue");
    expect(stem).toMatch(/^battle-order-round-2-\d{4}-\d{2}-\d{2}$/);
  });

  it("falls back when the name has no usable characters", () => {
    expect(exportFilenameStem("???", "queue")).toMatch(/^queue-\d{4}-\d{2}-\d{2}$/);
  });

  it("caps runaway names at 60 slug characters", () => {
    const stem = exportFilenameStem("x".repeat(200), "queue");
    const [slug] = stem.split(/-\d{4}-\d{2}-\d{2}$/);
    expect(slug).toHaveLength(60);
  });
});

describe("filenameFromDisposition", () => {
  it("prefers the RFC 5987 form and decodes it", () => {
    expect(
      filenameFromDisposition(
        "attachment; filename=\"fallback.json\"; filename*=utf-8''party%20resources.initiative-counter-group.json"
      )
    ).toBe("party resources.initiative-counter-group.json");
  });

  it("reads the plain quoted form", () => {
    expect(filenameFromDisposition('attachment; filename="rotation.initiative-queue.json"')).toBe(
      "rotation.initiative-queue.json"
    );
  });

  it("returns null when absent", () => {
    expect(filenameFromDisposition(undefined)).toBeNull();
  });
});
