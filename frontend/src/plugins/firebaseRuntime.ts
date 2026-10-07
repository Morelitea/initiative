import { registerPlugin } from "@capacitor/core";

export interface FirebaseRuntimePlugin {
  /**
   * Initialize Firebase with configuration from the backend server.
   * This allows self-hosted instances to use push notifications without rebuilding the APK.
   *
   * @param options - Configuration options
   * @returns Promise with success status. An iPhone build also says which APNs
   *   environment its tokens belong to (`sandbox` for a debug build); older
   *   builds leave it out, which means `production`.
   */
  initialize(options: { serverUrl: string }): Promise<{
    success: boolean;
    message?: string;
    apnsEnvironment?: "production" | "sandbox";
  }>;

  /**
   * Check if Firebase is already initialized.
   *
   * @returns Promise with initialization status
   */
  isInitialized(): Promise<{ initialized: boolean }>;

  /**
   * Clear stored Firebase configuration.
   * Useful when user wants to change server or reset push notifications.
   *
   * @returns Promise with success status
   */
  clearConfig(): Promise<{ success: boolean }>;
}

const FirebaseRuntime = registerPlugin<FirebaseRuntimePlugin>("FirebaseRuntime", {
  web: () => ({
    // Web implementation (no-op, Firebase not needed on web)
    initialize: async () => ({ success: false, message: "Not supported on web" }),
    isInitialized: async () => ({ initialized: false }),
    clearConfig: async () => ({ success: true }),
  }),
});

export default FirebaseRuntime;
