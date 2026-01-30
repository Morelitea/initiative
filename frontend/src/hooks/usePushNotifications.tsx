import { useEffect, useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { PushNotifications, type PermissionStatus } from "@capacitor/push-notifications";
import { Capacitor } from "@capacitor/core";
import type { PluginListenerHandle } from "@capacitor/core";

import { apiClient } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";
import FirebaseRuntime from "@/plugins/firebaseRuntime";

export type PermissionState = PermissionStatus["receive"];

interface UsePushNotificationsReturn {
  permissionStatus: PermissionState;
  requestPermission: () => Promise<void>;
  isSupported: boolean;
}

export const usePushNotifications = (): UsePushNotificationsReturn => {
  const { user } = useAuth();
  const { isNativePlatform, serverUrl } = useServer();
  const router = useRouter();
  const [permissionStatus, setPermissionStatus] = useState<PermissionState>("prompt");
  const [fcmEnabled, setFcmEnabled] = useState<boolean>(false);

  useEffect(() => {
    if (!isNativePlatform || !user) {
      return;
    }

    let registrationListener: PluginListenerHandle;
    let registrationErrorListener: PluginListenerHandle;
    let pushReceivedListener: PluginListenerHandle;
    let pushActionListener: PluginListenerHandle;

    const setupListeners = async () => {
      try {
        // Initialize Firebase with runtime configuration from backend
        if (!serverUrl) {
          console.log("No server URL configured, skipping push notification setup");
          return;
        }

        try {
          const initResult = await FirebaseRuntime.initialize({ serverUrl });

          if (!initResult.success) {
            console.log(
              "Firebase initialization skipped:",
              initResult.message || "FCM not configured on backend"
            );
            setFcmEnabled(false);
            return;
          }

          console.log("Firebase initialized successfully for push notifications");
          setFcmEnabled(true);
        } catch (err) {
          console.error("Failed to initialize Firebase:", err);
          setFcmEnabled(false);
          return;
        }

        // Check current permission status
        const permissions = await PushNotifications.checkPermissions();
        setPermissionStatus(permissions.receive);

        // Register listeners
        registrationListener = await PushNotifications.addListener(
          "registration",
          async (token) => {
            console.log("Push registration success, token:", token.value);
            // Send token to backend
            try {
              await apiClient.post("/push/register", {
                push_token: token.value,
                platform: Capacitor.getPlatform(),
              });
              console.log("Push token registered with backend");
            } catch (err) {
              console.error("Failed to register push token with backend:", err);
            }
          }
        );

        registrationErrorListener = await PushNotifications.addListener(
          "registrationError",
          (error) => {
            console.error("Push registration error:", error);
          }
        );

        pushReceivedListener = await PushNotifications.addListener(
          "pushNotificationReceived",
          (notification) => {
            // Handle foreground notification
            console.log("Push notification received (foreground):", notification);
            // The system will display the notification automatically
            // You could show a custom in-app notification here if desired
          }
        );

        pushActionListener = await PushNotifications.addListener(
          "pushNotificationActionPerformed",
          (notification) => {
            // Handle notification tap (navigate to target)
            console.log("Push notification action performed:", notification);
            const data = notification.notification.data;
            if (data.target_path && data.guild_id) {
              const targetPath = data.target_path as string;
              const guildId = data.guild_id as string;
              router.navigate({
                to: "/navigate",
                search: { guild_id: guildId, target: targetPath },
              });
            }
          }
        );

        // Register if already granted
        if (permissions.receive === "granted") {
          try {
            await PushNotifications.register();
          } catch (err) {
            console.error("Failed to register for push notifications:", err);
            // Don't crash the app if registration fails (e.g., in emulator or if FCM not configured)
          }
        }
      } catch (err) {
        console.error("Failed to setup push notifications:", err);
        // Don't crash the app if setup fails
      }
    };

    void setupListeners().catch((err) => {
      console.error("Failed to setup push notification listeners:", err);
      // Don't crash the app if setup fails
    });

    return () => {
      // Cleanup listeners
      void registrationListener?.remove();
      void registrationErrorListener?.remove();
      void pushReceivedListener?.remove();
      void pushActionListener?.remove();
    };
  }, [user, isNativePlatform, serverUrl, router]);

  const requestPermission = async () => {
    if (!isNativePlatform) {
      console.warn("Push notifications not supported on web");
      return;
    }

    if (!serverUrl) {
      console.warn("No server URL configured, cannot enable push notifications");
      return;
    }

    // Initialize Firebase if not already done
    if (!fcmEnabled) {
      try {
        const initResult = await FirebaseRuntime.initialize({ serverUrl });

        if (!initResult.success) {
          console.warn(
            "Firebase initialization failed:",
            initResult.message || "FCM not configured on backend"
          );
          return;
        }

        setFcmEnabled(true);
        console.log("Firebase initialized successfully");
      } catch (err) {
        console.error("Failed to initialize Firebase:", err);
        return;
      }
    }

    try {
      const result = await PushNotifications.requestPermissions();
      setPermissionStatus(result.receive);

      if (result.receive === "granted") {
        try {
          await PushNotifications.register();
        } catch (err) {
          console.error("Failed to register for push notifications:", err);
          // Don't crash the app if registration fails (e.g., in emulator or if FCM not configured)
        }
      }
    } catch (err) {
      console.error("Failed to request push notification permissions:", err);
      // Don't crash the app if permission request fails
    }
  };

  return {
    permissionStatus,
    requestPermission,
    isSupported: isNativePlatform && fcmEnabled,
  };
};
