import { app } from "./app.mjs";
import { updater } from "./autoUpdater.mjs";

/** Updates come only from the project's own releases. */
const RELEASES = "https://github.com/beyonders-studio/initiative/releases/download";

/** "1.2.3" and nothing else: each part digits only. */
const isReleaseVersion = (version: string) => {
  const parts = version.split(".");
  return (
    parts.length === 3 && parts.every((p) => p !== "" && [...p].every((c) => c >= "0" && c <= "9"))
  );
};

/**
 * Installs a newer desktop app, the one a server's update needs, from the
 * release that carries it. Windows and Debian builds can replace themselves;
 * a Mac app cannot until it is signed with a developer certificate, and a
 * development run has nothing installed to replace.
 */
export class DesktopUpdater {
  static __capacitorElectronPlugin = {
    name: "DesktopUpdater",
    methods: ["supported", "download", "install"],
  };

  async supported() {
    return {
      supported: app.isPackaged && (process.platform === "win32" || process.platform === "linux"),
    };
  }

  /** Download the app of `version`, to install now or when the app quits. */
  async download({ version }: { version: string }) {
    if (!(await this.supported()).supported) {
      throw new Error("This app cannot update itself.");
    }
    if (!isReleaseVersion(version)) {
      throw new Error(`${version} is not a release version.`);
    }
    const autoUpdater = updater();
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.setFeedURL({ provider: "generic", url: `${RELEASES}/v${version}` });
    const check = await autoUpdater.checkForUpdates();
    if (!check?.isUpdateAvailable) {
      throw new Error(`Release ${version} has no newer app for this computer.`);
    }
    await autoUpdater.downloadUpdate();
    return { version: check.updateInfo.version };
  }

  /** Close the app and install the downloaded one, then open it again. */
  async install() {
    updater().quitAndInstall(false, true);
  }
}
