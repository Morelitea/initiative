package com.morelitea.initiative;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;
import android.util.Log;

/**
 * Manages notification channels for different types of push notifications.
 * Android O (API 26) and above require notification channels for all notifications.
 */
public class NotificationChannelManager {
    private static final String TAG = "NotificationChannels";

    // Channel IDs - must match backend notification types exactly
    public static final String CHANNEL_TASK_ASSIGNMENT = "task_assignment";
    public static final String CHANNEL_INITIATIVE_ADDED = "initiative_added";
    public static final String CHANNEL_PROJECT_ADDED = "project_added";
    public static final String CHANNEL_USER_PENDING_APPROVAL = "user_pending_approval";
    public static final String CHANNEL_MENTION = "mention";
    public static final String CHANNEL_DEFAULT = "default";

    /**
     * Create all notification channels.
     * Safe to call multiple times - channels are only created once.
     *
     * @param context Application context
     */
    public static void createNotificationChannels(Context context) {
        // Channels only needed on Android O (API 26) and above
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationManager notificationManager =
            (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);

        if (notificationManager == null) {
            Log.e(TAG, "NotificationManager not available");
            return;
        }

        // 1. Task Assignment Channel
        NotificationChannel taskChannel = new NotificationChannel(
            CHANNEL_TASK_ASSIGNMENT,
            "Task Assignments",
            NotificationManager.IMPORTANCE_HIGH
        );
        taskChannel.setDescription("Notifications when you're assigned to a task");
        taskChannel.enableVibration(true);
        taskChannel.setShowBadge(true);
        notificationManager.createNotificationChannel(taskChannel);

        // 2. Initiative Added Channel
        NotificationChannel initiativeChannel = new NotificationChannel(
            CHANNEL_INITIATIVE_ADDED,
            "Initiative Invites",
            NotificationManager.IMPORTANCE_DEFAULT
        );
        initiativeChannel.setDescription("Notifications when you're added to an initiative");
        initiativeChannel.enableVibration(true);
        initiativeChannel.setShowBadge(true);
        notificationManager.createNotificationChannel(initiativeChannel);

        // 3. Project Added Channel
        NotificationChannel projectChannel = new NotificationChannel(
            CHANNEL_PROJECT_ADDED,
            "New Projects",
            NotificationManager.IMPORTANCE_DEFAULT
        );
        projectChannel.setDescription("Notifications when projects are created in your initiatives");
        projectChannel.enableVibration(true);
        projectChannel.setShowBadge(true);
        notificationManager.createNotificationChannel(projectChannel);

        // 4. User Pending Approval Channel
        NotificationChannel userApprovalChannel = new NotificationChannel(
            CHANNEL_USER_PENDING_APPROVAL,
            "User Approvals",
            NotificationManager.IMPORTANCE_DEFAULT
        );
        userApprovalChannel.setDescription("Notifications when new users request access");
        userApprovalChannel.enableVibration(true);
        userApprovalChannel.setShowBadge(true);
        notificationManager.createNotificationChannel(userApprovalChannel);

        // 5. Mentions Channel
        NotificationChannel mentionChannel = new NotificationChannel(
            CHANNEL_MENTION,
            "Mentions",
            NotificationManager.IMPORTANCE_HIGH
        );
        mentionChannel.setDescription("Notifications when someone mentions you in a document");
        mentionChannel.enableVibration(true);
        mentionChannel.setShowBadge(true);
        notificationManager.createNotificationChannel(mentionChannel);

        // 6. Default Channel (fallback)
        NotificationChannel defaultChannel = new NotificationChannel(
            CHANNEL_DEFAULT,
            "General Notifications",
            NotificationManager.IMPORTANCE_DEFAULT
        );
        defaultChannel.setDescription("General app notifications");
        defaultChannel.enableVibration(true);
        defaultChannel.setShowBadge(true);
        notificationManager.createNotificationChannel(defaultChannel);

        Log.i(TAG, "Notification channels created successfully");
    }

    /**
     * Get the channel ID for a notification type.
     * Maps backend notification types to Android channel IDs.
     *
     * @param notificationType Backend notification type (e.g., "task_assignment")
     * @return Android channel ID
     */
    public static String getChannelIdForType(String notificationType) {
        if (notificationType == null) {
            return CHANNEL_DEFAULT;
        }

        switch (notificationType) {
            case "task_assignment":
                return CHANNEL_TASK_ASSIGNMENT;
            case "initiative_added":
                return CHANNEL_INITIATIVE_ADDED;
            case "project_added":
                return CHANNEL_PROJECT_ADDED;
            case "user_pending_approval":
                return CHANNEL_USER_PENDING_APPROVAL;
            case "mention":
                return CHANNEL_MENTION;
            default:
                return CHANNEL_DEFAULT;
        }
    }
}
