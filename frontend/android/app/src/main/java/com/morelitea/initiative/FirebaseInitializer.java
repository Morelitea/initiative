package com.morelitea.initiative;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import com.google.firebase.FirebaseApp;
import com.google.firebase.FirebaseOptions;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

public class FirebaseInitializer {
    private static final String TAG = "FirebaseInitializer";
    private static final String PREFS_NAME = "FirebaseConfig";
    private static final String KEY_PROJECT_ID = "project_id";
    private static final String KEY_APPLICATION_ID = "application_id";
    private static final String KEY_API_KEY = "api_key";
    private static final String KEY_SENDER_ID = "sender_id";
    private static final String KEY_ENABLED = "enabled";
    private static final String KEY_SERVER_URL = "server_url";

    /**
     * Initialize Firebase with runtime configuration from backend.
     * This allows self-hosted instances to use push notifications without rebuilding the APK.
     *
     * @param context Application context
     * @param serverUrl Backend server URL (from Capacitor config or user input)
     * @return true if Firebase was initialized successfully, false otherwise
     */
    public static boolean initializeFirebase(Context context, String serverUrl) {
        // Check if Firebase is already initialized
        if (!FirebaseApp.getApps(context).isEmpty()) {
            Log.d(TAG, "Firebase already initialized");
            return true;
        }

        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);

        // Check if we need to fetch new config (server URL changed or no config stored)
        String storedServerUrl = prefs.getString(KEY_SERVER_URL, "");
        if (!serverUrl.equals(storedServerUrl) || !prefs.contains(KEY_PROJECT_ID)) {
            Log.d(TAG, "Fetching FCM config from backend: " + serverUrl);
            if (!fetchAndStoreConfig(context, serverUrl, prefs)) {
                Log.w(TAG, "Failed to fetch FCM config, push notifications disabled");
                return false;
            }
        }

        // Check if FCM is enabled on backend
        boolean enabled = prefs.getBoolean(KEY_ENABLED, false);
        if (!enabled) {
            Log.d(TAG, "FCM not enabled on backend, push notifications disabled");
            return false;
        }

        // Load config from SharedPreferences
        String projectId = prefs.getString(KEY_PROJECT_ID, null);
        String applicationId = prefs.getString(KEY_APPLICATION_ID, null);
        String apiKey = prefs.getString(KEY_API_KEY, null);
        String senderId = prefs.getString(KEY_SENDER_ID, null);

        if (projectId == null || applicationId == null || apiKey == null) {
            Log.e(TAG, "Incomplete FCM config, push notifications disabled");
            return false;
        }

        try {
            // Initialize Firebase with runtime config
            FirebaseOptions options = new FirebaseOptions.Builder()
                .setProjectId(projectId)
                .setApplicationId(applicationId)
                .setApiKey(apiKey)
                .setGcmSenderId(senderId)
                .build();

            FirebaseApp.initializeApp(context, options);
            Log.i(TAG, "Firebase initialized successfully with project: " + projectId);
            return true;
        } catch (Exception e) {
            Log.e(TAG, "Failed to initialize Firebase: " + e.getMessage(), e);
            return false;
        }
    }

    /**
     * Fetch FCM configuration from backend API and store in SharedPreferences.
     *
     * @param context Application context
     * @param serverUrl Backend server URL
     * @param prefs SharedPreferences to store config
     * @return true if config was fetched successfully, false otherwise
     */
    private static boolean fetchAndStoreConfig(Context context, String serverUrl, SharedPreferences prefs) {
        final CountDownLatch latch = new CountDownLatch(1);
        final boolean[] success = {false};

        // Fetch config in background thread (network operation)
        new Thread(() -> {
            HttpURLConnection connection = null;
            BufferedReader reader = null;
            try {
                // Remove trailing slash from server URL
                String baseUrl = serverUrl.endsWith("/") ? serverUrl.substring(0, serverUrl.length() - 1) : serverUrl;
                String configUrl = baseUrl + "/api/v1/settings/fcm-config";

                Log.d(TAG, "Fetching FCM config from: " + configUrl);

                // Validate HTTPS for security (allow HTTP only for localhost and private IPs)
                if (configUrl.startsWith("http://")) {
                    String host = new URL(configUrl).getHost();
                    boolean isLocalHost = host.equals("localhost") || host.equals("127.0.0.1") || host.equals("0.0.0.0");
                    boolean isPrivateIP = host.startsWith("192.168.") || host.startsWith("10.") ||
                                         host.matches("172\\.(1[6-9]|2[0-9]|3[0-1])\\..*");

                    if (!isLocalHost && !isPrivateIP) {
                        Log.e(TAG, "Server URL must use HTTPS for security (HTTP only allowed for localhost/private IPs)");
                        return;
                    }

                    Log.w(TAG, "Using HTTP connection - only use this for local development");
                }

                URL url = new URL(configUrl);
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(10000); // 10 seconds
                connection.setReadTimeout(10000);
                connection.setRequestProperty("Accept", "application/json");

                int responseCode = connection.getResponseCode();
                if (responseCode != HttpURLConnection.HTTP_OK) {
                    Log.e(TAG, "Backend returned error: " + responseCode);
                    return;
                }

                // Read response
                reader = new BufferedReader(new InputStreamReader(connection.getInputStream()));
                StringBuilder response = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    response.append(line);
                }

                // Parse JSON response
                JSONObject json = new JSONObject(response.toString());
                boolean enabled = json.optBoolean("enabled", false);

                if (!enabled) {
                    Log.d(TAG, "FCM not enabled on backend");
                    prefs.edit()
                        .putBoolean(KEY_ENABLED, false)
                        .putString(KEY_SERVER_URL, serverUrl)
                        .apply();
                    success[0] = true;
                    return;
                }

                String projectId = json.optString("project_id", null);
                String applicationId = json.optString("application_id", null);
                String apiKey = json.optString("api_key", null);
                String senderId = json.optString("sender_id", null);

                if (projectId == null || applicationId == null || apiKey == null) {
                    Log.e(TAG, "Incomplete FCM config from backend");
                    return;
                }

                // Store config
                prefs.edit()
                    .putBoolean(KEY_ENABLED, true)
                    .putString(KEY_PROJECT_ID, projectId)
                    .putString(KEY_APPLICATION_ID, applicationId)
                    .putString(KEY_API_KEY, apiKey)
                    .putString(KEY_SENDER_ID, senderId)
                    .putString(KEY_SERVER_URL, serverUrl)
                    .apply();

                Log.i(TAG, "FCM config stored successfully");
                success[0] = true;

            } catch (Exception e) {
                Log.e(TAG, "Error fetching FCM config: " + e.getMessage(), e);
            } finally {
                if (reader != null) {
                    try {
                        reader.close();
                    } catch (Exception ignored) {}
                }
                if (connection != null) {
                    connection.disconnect();
                }
                latch.countDown();
            }
        }).start();

        // Wait for fetch to complete (max 15 seconds)
        try {
            latch.await(15, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Log.e(TAG, "Timeout waiting for FCM config fetch", e);
        }

        return success[0];
    }

    /**
     * Clear stored FCM configuration.
     * Call this when user changes server URL or wants to reset push notifications.
     *
     * @param context Application context
     */
    public static void clearConfig(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().clear().apply();
        Log.i(TAG, "FCM config cleared");
    }
}
