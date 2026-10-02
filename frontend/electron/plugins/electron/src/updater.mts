import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, normalize, sep } from "node:path";

import { app } from "electron";
import { unzipSync } from "fflate";

type BundleStatus = "success" | "error" | "pending" | "downloading";

interface BundleInfo {
  id: string;
  version: string;
  downloaded: string;
  checksum: string;
  status: BundleStatus;
}

interface State {
  bundles: BundleInfo[];
  /** The bundle last switched to, until it confirms it started. */
  applied: string | null;
  /** The app version these bundles were downloaded under. */
  native: string | null;
}

interface BundlesService {
  getActiveBundlePath(): string | null;
  setActiveBundle(directory: string | null, options?: { bootWatchdog?: boolean }): Promise<void>;
  notifyBootReady(): void;
}

/** The web code the app was installed with. */
const BUILTIN: BundleInfo = {
  id: "builtin",
  version: "builtin",
  downloaded: "",
  checksum: "",
  status: "success",
};

/**
 * What `@capgo/capacitor-updater` does on a phone, for the calls the app makes:
 * a web bundle downloaded from the server, checked against the sha256 its
 * signed statement names, unpacked beside the app's other data and switched
 * to. The platform rolls back to the previous bundle when a new one does not
 * confirm it started.
 */
export class CapacitorUpdater {
  static __capacitorElectronPlugin = {
    name: "CapacitorUpdater",
    methods: ["current", "list", "download", "set", "delete", "notifyAppReady"],
  };

  private readonly bundles: BundlesService;

  constructor({ services }: { services: { bundles: BundlesService } }) {
    this.bundles = services.bundles;
  }

  /** Before the first window: a newly installed app starts on its own web code. */
  async load() {
    const state = this.settle();
    const native = app.getVersion();
    if (state.native === native) return;
    if (state.native !== null) {
      await this.bundles.setActiveBundle(null);
      rmSync(this.root, { recursive: true, force: true });
    }
    this.write({ bundles: state.native === null ? state.bundles : [], applied: null, native });
  }

  async current() {
    const active = this.bundles.getActiveBundlePath();
    const bundle = this.read().bundles.find((b) => this.dir(b.id) === active) ?? BUILTIN;
    return { bundle, native: app.getVersion() };
  }

  async list() {
    return { bundles: this.read().bundles };
  }

  async download({ url, version, checksum }: { url: string; version: string; checksum: string }) {
    const id = randomUUID();
    const state = this.read();
    state.bundles.push({
      id,
      version,
      downloaded: new Date().toISOString(),
      checksum,
      status: "downloading",
    });
    this.write(state);
    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`The bundle download answered ${response.status}.`);
      }
      const zip = new Uint8Array(await response.arrayBuffer());
      if (createHash("sha256").update(zip).digest("hex") !== checksum) {
        throw new Error("The bundle does not match its checksum.");
      }
      this.unpack(zip, this.dir(id));
      return this.mark(id, "pending");
    } catch (error) {
      rmSync(this.dir(id), { recursive: true, force: true });
      this.mark(id, "error");
      throw error;
    }
  }

  async set({ id }: { id: string }) {
    const state = this.read();
    const bundle = state.bundles.find((b) => b.id === id);
    if (!bundle || (bundle.status !== "pending" && bundle.status !== "success")) {
      throw new Error(`Bundle ${id} is not ready.`);
    }
    this.write({ ...state, applied: id });
    await this.bundles.setActiveBundle(this.dir(id));
  }

  async delete({ id }: { id: string }) {
    if (this.bundles.getActiveBundlePath() === this.dir(id)) {
      throw new Error(`Bundle ${id} is the one running.`);
    }
    rmSync(this.dir(id), { recursive: true, force: true });
    const state = this.read();
    this.write({ ...state, bundles: state.bundles.filter((b) => b.id !== id) });
  }

  /** The running bundle started. The ones it replaced are no longer needed. */
  async notifyAppReady() {
    this.bundles.notifyBootReady();
    const state = this.settle();
    if (state.applied !== null) {
      const applied = state.applied;
      for (const bundle of state.bundles) {
        if (bundle.id !== applied && bundle.status !== "downloading") {
          rmSync(this.dir(bundle.id), { recursive: true, force: true });
        }
      }
      this.write({
        ...state,
        applied: null,
        bundles: state.bundles
          .filter((b) => b.id === applied || b.status === "downloading")
          .map((b) => (b.id === applied ? { ...b, status: "success" } : b)),
      });
    }
    return { bundle: (await this.current()).bundle };
  }

  /** A bundle switched to that is not the one running was rolled back. */
  private settle(): State {
    const state = this.read();
    if (state.applied !== null && this.bundles.getActiveBundlePath() !== this.dir(state.applied)) {
      const failed = state.applied;
      const settled: State = {
        ...state,
        applied: null,
        bundles: state.bundles.map((b) => (b.id === failed ? { ...b, status: "error" } : b)),
      };
      this.write(settled);
      return settled;
    }
    return state;
  }

  /** Every entry lands inside the bundle's own folder. */
  private unpack(zip: Uint8Array, target: string) {
    for (const [name, data] of Object.entries(unzipSync(zip))) {
      if (name.endsWith("/")) continue;
      const path = normalize(join(target, name));
      if (!path.startsWith(target + sep)) {
        throw new Error(`The bundle holds ${name}, outside its folder.`);
      }
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, data);
    }
    if (!existsSync(join(target, "index.html"))) {
      throw new Error("The bundle has no index.html.");
    }
  }

  private mark(id: string, status: BundleStatus): BundleInfo {
    const state = this.read();
    const bundles = state.bundles.map((b) => (b.id === id ? { ...b, status } : b));
    this.write({ ...state, bundles });
    return bundles.find((b) => b.id === id) as BundleInfo;
  }

  private get root() {
    return join(app.getPath("userData"), "updates");
  }

  private dir(id: string) {
    return join(this.root, id);
  }

  private get stateFile() {
    return join(this.root, "bundles.json");
  }

  private read(): State {
    try {
      return JSON.parse(readFileSync(this.stateFile, "utf8")) as State;
    } catch {
      return { bundles: [], applied: null, native: null };
    }
  }

  private write(state: State) {
    mkdirSync(this.root, { recursive: true });
    writeFileSync(this.stateFile, JSON.stringify(state, null, 2));
  }
}
