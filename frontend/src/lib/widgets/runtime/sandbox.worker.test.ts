/**
 * Where this worker's bundle lands is part of its contract.
 *
 * The response that serves it carries its own Content-Security-Policy, which
 * the backend attaches by matching the built file's path
 * (`_WIDGET_SANDBOX_ASSET_PREFIX` in `backend/app/main.py`). Vite decides that
 * path from two things — the worker output pattern and this file's name — so
 * both are pinned here, and the backend pins the literal it matches. A rename
 * on either side fails a test rather than quietly serving the wrong header.
 */

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/** Keep in step with `_WIDGET_SANDBOX_ASSET_PREFIX` in backend/app/main.py. */
const WORKER_OUTPUT = "assets/workers/[name]-[hash].js";

const resolve = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));

describe("widget sandbox worker asset", () => {
  it("is emitted into the directory the backend matches", () => {
    const config = readFileSync(resolve("../../../../vite.config.ts"), "utf8");
    expect(config).toContain(`entryFileNames: "${WORKER_OUTPUT}"`);
  });

  it("keeps the entry name the backend matches", () => {
    // `[name]` resolves to the worker entry's basename, so the built file is
    // `assets/workers/sandbox.worker-<hash>.js`.
    expect(existsSync(resolve("./sandbox.worker.ts"))).toBe(true);
    expect(WORKER_OUTPUT.replace("[name]", "sandbox.worker")).toBe(
      "assets/workers/sandbox.worker-[hash].js"
    );
  });
});
