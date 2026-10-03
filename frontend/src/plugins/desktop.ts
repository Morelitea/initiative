import { registerPlugin } from "@capacitor/core";

/** The words the tray shows, in the person's language. */
export interface DesktopLabels {
  open: string;
  quit: string;
  tooltip: string;
}

/** The desktop app's own shell (`frontend/electron/plugins`). */
export interface DesktopPlugin {
  /** Show a system notification; clicking it reports `tag` back. */
  notify(options: { title: string; body?: string; tag: string }): Promise<void>;
  /** The unread count on the dock, launcher, taskbar and tray; `labels` once known. */
  setBadge(options: { count: number; overlay?: string; labels?: DesktopLabels }): Promise<void>;
  getSettings(): Promise<{ tray: boolean; keepRunning: boolean; openAtLogin: boolean }>;
  setKeepRunning(options: { enabled: boolean }): Promise<void>;
  setOpenAtLogin(options: { enabled: boolean }): Promise<void>;
  addListener(
    eventName: "notificationClicked",
    listener: (event: { tag: string }) => void
  ): Promise<{ remove: () => Promise<void> }>;
}

const Desktop = registerPlugin<DesktopPlugin>("Desktop");

export default Desktop;
