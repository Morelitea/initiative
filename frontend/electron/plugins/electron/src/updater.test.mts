/**
 * The desktop app's bundle updater: a bundle is kept only when it matches its
 * checksum and stays inside its folder, one the platform rolled back is not
 * offered again, and only bundles it downloaded can be deleted.
 */
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { strToU8, zipSync } from "fflate";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const paths = vi.hoisted(() => ({ userData: "" }));
vi.mock("electron", () => ({
  app: { getPath: () => paths.userData, getVersion: () => "1.0.0" },
}));

import { CapacitorUpdater } from "./updater.mjs";

const zip = (files: Record<string, string>) =>
  zipSync(Object.fromEntries(Object.entries(files).map(([name, body]) => [name, strToU8(body)])));
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

/** The platform's bundle service, switching where it is told. */
const platform = () => {
  let active: string | null = null;
  return {
    getActiveBundlePath: () => active,
    setActiveBundle: vi.fn(async (directory: string | null) => {
      active = directory;
    }),
    notifyBootReady: vi.fn(),
    rollBack: () => {
      active = null;
    },
  };
};

const serve = (bytes: Uint8Array) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(bytes))
  );

beforeEach(() => {
  paths.userData = mkdtempSync(join(tmpdir(), "initiative-updater-"));
});

afterEach(() => {
  rmSync(paths.userData, { recursive: true, force: true });
});

describe("the desktop bundle updater", () => {
  it("keeps a bundle that matches its checksum and refuses one that does not", async () => {
    const bundles = platform();
    const updater = new CapacitorUpdater({ services: { bundles } });
    const bytes = zip({ "index.html": "<!doctype html>", "assets/app.js": "" });
    serve(bytes);

    const kept = await updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) });
    await expect(
      updater.download({ url: "u", version: "2.0.1", checksum: "0".repeat(64) })
    ).rejects.toThrow(/checksum/);

    expect(kept.status).toBe("pending");
    expect(existsSync(join(paths.userData, "updates", kept.id, "assets", "app.js"))).toBe(true);
    const { bundles: listed } = await updater.list();
    expect(listed.map((b) => `${b.version}:${b.status}`)).toEqual(["2.0.0:pending", "2.0.1:error"]);
  });

  it("refuses a bundle with an entry outside its folder", async () => {
    const updater = new CapacitorUpdater({ services: { bundles: platform() } });
    const bytes = zip({ "index.html": "", "../outside.txt": "" });
    serve(bytes);

    await expect(
      updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) })
    ).rejects.toThrow(/outside its folder/);
    expect(existsSync(join(paths.userData, "updates", "outside.txt"))).toBe(false);
  });

  it("marks a bundle the platform rolled back as failed", async () => {
    const bundles = platform();
    const updater = new CapacitorUpdater({ services: { bundles } });
    const bytes = zip({ "index.html": "" });
    serve(bytes);
    const bundle = await updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) });

    await updater.set({ id: bundle.id });
    bundles.rollBack();
    await updater.notifyAppReady();

    expect((await updater.list()).bundles[0].status).toBe("error");
    expect((await updater.current()).bundle.id).toBe("builtin");
  });

  it("deletes only a bundle it downloaded", async () => {
    const updater = new CapacitorUpdater({ services: { bundles: platform() } });

    await expect(updater.delete({ id: ".." })).rejects.toThrow(/not one this app downloaded/);
    expect(existsSync(paths.userData)).toBe(true);
  });
});
