package com.morelitea.initiative;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Capacitor plugin for runtime Firebase initialization.
 * Allows self-hosted instances to configure Firebase without rebuilding the APK.
 */
@CapacitorPlugin(name = "FirebaseRuntime")
public class FirebaseRuntimePlugin extends Plugin {

    /**
     * Initialize Firebase with configuration from the backend server.
     *
     * @param call Plugin call with serverUrl parameter
     */
    @PluginMethod
    public void initialize(PluginCall call) {
        String serverUrl = call.getString("serverUrl");

        if (serverUrl == null || serverUrl.isEmpty()) {
            call.reject("Server URL is required");
            return;
        }

        // Initialize Firebase (network call happens in background thread inside initializeFirebase)
        getActivity().runOnUiThread(() -> {
            boolean success = FirebaseInitializer.initializeFirebase(
                getContext(),
                serverUrl
            );

            JSObject result = new JSObject();
            result.put("success", success);

            if (success) {
                call.resolve(result);
            } else {
                result.put("message", "Firebase initialization failed or FCM not configured");
                call.resolve(result); // Not an error - just means FCM is disabled
            }
        });
    }

    /**
     * Check if Firebase is already initialized.
     *
     * @param call Plugin call
     */
    @PluginMethod
    public void isInitialized(PluginCall call) {
        boolean initialized = com.google.firebase.FirebaseApp.getApps(getContext()).size() > 0;

        JSObject result = new JSObject();
        result.put("initialized", initialized);
        call.resolve(result);
    }

    /**
     * Clear stored Firebase configuration.
     * Useful when user wants to change server or reset push notifications.
     *
     * @param call Plugin call
     */
    @PluginMethod
    public void clearConfig(PluginCall call) {
        FirebaseInitializer.clearConfig(getContext());

        JSObject result = new JSObject();
        result.put("success", true);
        call.resolve(result);
    }
}
