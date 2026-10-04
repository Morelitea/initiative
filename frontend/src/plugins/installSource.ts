import { registerPlugin } from "@capacitor/core";

export interface InstallSourcePlugin {
  /** The package that installed the app (Google Play is "com.android.vending"); absent when unknown. */
  get(): Promise<{ installer?: string }>;
}

/** Google Play's package name, as Android reports the installer. */
export const PLAY_STORE_INSTALLER = "com.android.vending";

const InstallSource = registerPlugin<InstallSourcePlugin>("InstallSource", {
  web: () => ({ get: async () => ({}) }),
});

export default InstallSource;
