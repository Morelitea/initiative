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

  // Each of these leaves the runtime in a different state than it read in:
  // never booted, rebuilt after going quiet, or disposed by the memory cap.
  it.each([SandboxErrorCode.UNAVAILABLE, SandboxErrorCode.TIMEOUT, SandboxErrorCode.OUT_OF_MEMORY])(
    "reads again after %s, and keeps what it then gets",
    async (code) => {
      readMetaInSandbox.mockResolvedValueOnce({ ok: false, code }).mockResolvedValueOnce(META);
      const source = `// ${code}\nconst meta = { name: { en: 'Summary' } };`;

      expect(await readWidgetMeta(source)).toBeNull();
      expect(await readWidgetMeta(source)).not.toBeNull();
      expect(await readWidgetMeta(source)).not.toBeNull();
      // Two reads, not three: the failure was retried, the answer was kept.
      expect(readMetaInSandbox).toHaveBeenCalledTimes(2);
    }
  );

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
