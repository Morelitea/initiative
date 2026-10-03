// electron-updater's updater, through a module of the plugins' own, so a test
// can stand in for it without Electron installed. electron-updater is
// CommonJS and makes its updater on first use, so it is read when needed.
import electronUpdater from "electron-updater";

export const updater = () => electronUpdater.autoUpdater;
