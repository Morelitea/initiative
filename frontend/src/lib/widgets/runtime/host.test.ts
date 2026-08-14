/**
 * Host-side behaviour that the sandbox itself cannot express: what is kept
 * between calls. jsdom has no `Worker`, so these exercise the in-process path
 * with the sandbox stubbed — the caching rule is the same either way.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const readMetaInSandbox = vi.hoisted(() => vi.fn());

vi.mock("./sandbox", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./sandbox")>()),
  readMetaInSandbox,
}));

import { readWidgetMeta } from "./host";
import { SandboxErrorCode } from "./sandbox";

const META = { ok: true, value: { name: { en: "Summary" } } };

describe("readWidgetMeta", () => {
  beforeEach(() => {
    // Counts are per case; each case uses its own source, so the module-level
    // cache does not carry between them.
    readMetaInSandbox.mockReset();
  });

  it("reads again after the runtime failed, and keeps what it then gets", async () => {
    readMetaInSandbox
      .mockResolvedValueOnce({ ok: false, code: SandboxErrorCode.UNAVAILABLE })
      .mockResolvedValueOnce(META);
    const source = "// runtime failure\nconst meta = { name: { en: 'Summary' } };";

    expect(await readWidgetMeta(source)).toBeNull();
    expect(await readWidgetMeta(source)).not.toBeNull();
    expect(await readWidgetMeta(source)).not.toBeNull();
    // Two reads, not three: the failure was retried, the answer was kept.
    expect(readMetaInSandbox).toHaveBeenCalledTimes(2);
  });

  it("keeps a failure the module itself causes", async () => {
    readMetaInSandbox.mockResolvedValue({ ok: false, code: SandboxErrorCode.THREW });
    const source = "// module failure\nthrow new Error('nope');";

    expect(await readWidgetMeta(source)).toBeNull();
    expect(await readWidgetMeta(source)).toBeNull();
    expect(readMetaInSandbox).toHaveBeenCalledTimes(1);
  });

  it("keeps a module that declares no meta", async () => {
    readMetaInSandbox.mockResolvedValue({ ok: true, value: null });
    const source = "// no meta\nconst render = () => ({ kind: 'empty' });";

    expect(await readWidgetMeta(source)).toBeNull();
    expect(await readWidgetMeta(source)).toBeNull();
    expect(readMetaInSandbox).toHaveBeenCalledTimes(1);
  });
});
