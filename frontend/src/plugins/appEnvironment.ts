import { registerPlugin } from "@capacitor/core";

export interface AppEnvironmentPlugin {
  /**
   * The package that installed the app (Google Play is "com.android.vending"; absent when
   * unknown), and whether this build may reach plain-HTTP servers (only a debug build does).
   */
  get(): Promise<{ installer?: string; cleartextPermitted?: boolean }>;
}

/** Google Play's package name, as Android reports the installer. */
export const PLAY_STORE_INSTALLER = "com.android.vending";

const AppEnvironment = registerPlugin<AppEnvironmentPlugin>("AppEnvironment", {
  web: () => ({ get: async () => ({}) }),
});

export default AppEnvironment;
