import { registerPlugin } from "@capacitor/core";

export interface AppEnvironmentPlugin {
  /**
   * The package that installed the app (Google Play is "com.android.vending"; absent when
   * unknown), and whether this build may reach plain-HTTP servers (only a debug build does).
   */
  get(): Promise<{ installer?: string; cleartextPermitted?: boolean }>;
  /**
   * The country of the store account this app sells under: the App Store storefront on iOS
   * (ISO 3166-1 alpha-3, e.g. "USA"), the Play billing country on a Play install (alpha-2).
   * Absent when the store cannot say, and on any other Android install. Native builds older
   * than this method reject the call.
   */
  storeCountry(): Promise<{ country?: string }>;
}

export { PLAY_STORE_INSTALLER } from "@/lib/playStore";

const AppEnvironment = registerPlugin<AppEnvironmentPlugin>("AppEnvironment", {
  web: () => ({ get: async () => ({}), storeCountry: async () => ({}) }),
});

export default AppEnvironment;
