import { registerPlugin } from "@capacitor/core";

/** The desktop app's own updater (`frontend/electron/plugins`). */
export interface DesktopUpdaterPlugin {
  /** Whether this app can replace itself: an installed Windows or Debian app. */
  supported(): Promise<{ supported: boolean }>;
  /** Download the app of `version`, from the release that carries it. */
  download(options: { version: string }): Promise<{ version: string }>;
  /** Close the app, install the downloaded one and open it again. */
  install(): Promise<void>;
}

const DesktopUpdater = registerPlugin<DesktopUpdaterPlugin>("DesktopUpdater", {
  web: () => ({
    supported: async () => ({ supported: false }),
    download: async () => {
      throw new Error("Only the desktop app updates itself.");
    },
    install: async () => {},
  }),
});

export default DesktopUpdater;
