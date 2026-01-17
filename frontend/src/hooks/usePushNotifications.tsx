import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PushNotifications, type PermissionStatus } from "@capacitor/push-notifications";
import { Capacitor } from "@capacitor/core";
import type { PluginListenerHandle } from "@capacitor/core";

import { apiClient } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";

export type PermissionState = PermissionStatus["receive"];

interface UsePushNotificationsReturn {
  permissionStatus: PermissionState;
  requestPermission: () => Promise<void>;
  isSupported: boolean;
}

export const usePushNotifications = (): UsePushNotificationsReturn => {
  const { user } = useAuth();
  const { isNativePlatform } = useServer();
  const navigate = useNavigate();
  const [permissionStatus, setPermissionStatus] = useState<PermissionState>("prompt");

  useEffect(() => {
    if (!isNativePlatform || !user) {
      return;
    }

    let registrationListener: PluginListenerHandle;
    let registrationErrorListener: PluginListenerHandle;
    let pushReceivedListener: PluginListenerHandle;
    let pushActionListener: PluginListenerHandle;

    const setupListeners = async () => {
      // Check current permission status
      const permissions = await PushNotifications.checkPermissions();
      setPermissionStatus(permissions.receive);

      // Register listeners
      registrationListener = await PushNotifications.addListener("registration", async (token) => {
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
      });

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
            navigate(`/navigate?guild_id=${guildId}&target=${encodeURIComponent(targetPath)}`);
          }
        }
      );

      // Register if already granted
      if (permissions.receive === "granted") {
        await PushNotifications.register();
      }
    };

    void setupListeners();

    return () => {
      // Cleanup listeners
      void registrationListener?.remove();
      void registrationErrorListener?.remove();
      void pushReceivedListener?.remove();
      void pushActionListener?.remove();
    };
  }, [user, isNativePlatform, navigate]);

  const requestPermission = async () => {
    if (!isNativePlatform) {
      console.warn("Push notifications not supported on web");
      return;
    }

    const result = await PushNotifications.requestPermissions();
    setPermissionStatus(result.receive);

    if (result.receive === "granted") {
      await PushNotifications.register();
    }
  };

  return {
    permissionStatus,
    requestPermission,
    isSupported: isNativePlatform,
  };
};
