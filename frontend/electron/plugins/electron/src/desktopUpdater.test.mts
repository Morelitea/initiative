/**
 * The desktop app replacing itself: only from the project's release of the
 * version asked for, and only where an installed app can.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => ({
  app: { isPackaged: true },
  autoUpdater: {
    autoDownload: true,
    autoInstallOnAppQuit: false,
    setFeedURL: vi.fn(),
    checkForUpdates: vi.fn(),
    downloadUpdate: vi.fn(),
    quitAndInstall: vi.fn(),
  },
}));
vi.mock("./app.mjs", () => ({ app: electron.app }));
vi.mock("./autoUpdater.mjs", () => ({ updater: () => electron.autoUpdater }));

import { DesktopUpdater } from "./desktopUpdater.mjs";

const onPlatform = (platform: NodeJS.Platform) =>
  vi.spyOn(process, "platform", "get").mockReturnValue(platform);

beforeEach(() => {
  electron.app.isPackaged = true;
  electron.autoUpdater.checkForUpdates.mockResolvedValue({
    isUpdateAvailable: true,
    updateInfo: { version: "0.80.0" },
  });
});

describe("the desktop app updater", () => {
  it("downloads the app from the release of the version asked for", async () => {
    onPlatform("win32");

    await expect(new DesktopUpdater().download({ version: "0.80.0" })).resolves.toEqual({
      version: "0.80.0",
    });
    expect(electron.autoUpdater.setFeedURL).toHaveBeenCalledWith({
      provider: "generic",
      url: "https://github.com/beyonders-studio/initiative/releases/download/v0.80.0",
    });
    expect(electron.autoUpdater.downloadUpdate).toHaveBeenCalled();
  });

  it.each(["0.80", "0.80.0/../x", "v0.80.0", ""])("refuses %j as a version", async (version) => {
    onPlatform("linux");

    await expect(new DesktopUpdater().download({ version })).rejects.toThrow(/release version/);
    expect(electron.autoUpdater.setFeedURL).not.toHaveBeenCalled();
  });

  it("leaves a Mac app and a development run to the download", async () => {
    onPlatform("darwin");
    expect((await new DesktopUpdater().supported()).supported).toBe(false);

    onPlatform("linux");
    electron.app.isPackaged = false;
    expect((await new DesktopUpdater().supported()).supported).toBe(false);
  });
});
