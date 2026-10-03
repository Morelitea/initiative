import { Capacitor } from "@capacitor/core";

import { getItem, setItem } from "@/lib/storage";
import DesktopUpdater from "@/plugins/desktopUpdater";

/** Whether the person said this computer may update the app without asking. */
const CONSENT_KEY = "initiative-desktop-auto-update";

/** Whether this is a desktop app that can replace itself with a newer one. */
export const desktopCanUpdate = async (): Promise<boolean> => {
  if (Capacitor.getPlatform() !== "electron") return false;
  try {
    return (await DesktopUpdater.supported()).supported;
  } catch {
    return false;
  }
};

export const autoUpdateConsented = (): boolean => getItem(CONSENT_KEY) === "true";

export const setAutoUpdateConsent = (allowed: boolean): void => {
  void setItem(CONSENT_KEY, String(allowed));
};
