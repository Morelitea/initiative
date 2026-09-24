---
icon: lucide/bell-ring
---

# Push notifications (Firebase)

Mobile push notifications are delivered through **Firebase Cloud Messaging (FCM)**. This is optional — Initiative works without it, and in-app and email notifications don't need it. Set it up only if you want alerts pushed to the mobile apps.

You enter everything in **Settings → Platform → Push notifications**, as the [owner](platform-roles.md), and the mobile app fetches what it needs from your server. You do **not** need to commit a `google-services.json` file into the app, and you don't need to restart anything.

## 1. Create a Firebase project

1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** (or pick an existing one) and follow the prompts.

## 2. Register an Android app

1. In the Firebase console, add an **Android** app.
2. Use the package name **`com.morelitea.initiative`** (it must match exactly).
3. Register the app and download the generated `google-services.json` — you'll read a few values out of it, not commit it.

## 3. Generate a service-account key

1. In **Project Settings → Service Accounts**, click **Generate New Private Key**.
2. Save the JSON file somewhere safe. **Never commit it to source control.**

## 4. Fill in the settings

In **Settings → Platform → Push notifications**, turn on **Send push notifications** and fill in:

| Field | From `google-services.json` | Or in the Firebase console |
|---|---|---|
| **Project ID** | `project_info.project_id` | Project Settings → General → Project ID |
| **App ID** | `client[0].client_info.mobilesdk_app_id` | Project Settings → General → Your Apps → App ID |
| **Web API key** | `client[0].api_key[0].current_key` | Project Settings → General → Web API Key |
| **Sender ID** | `project_info.project_number` | Project Settings → Cloud Messaging → Sender ID |

For **Service account key**, open the key file from step 3 and paste the whole thing, braces and all. The page won't save anything that isn't one complete JSON object, so a half-copied key gets caught before it's stored.

The key is write-only: once it's saved, the field shows that a key is there, and never shows the key. Leave it blank when editing the other fields and the saved key stays put.

??? techspec "Pre-filling from environment variables"
    On a fresh install's **first boot**, the `FCM_*` variables fill these settings in: `FCM_ENABLED`, `FCM_PROJECT_ID`, `FCM_APPLICATION_ID`, `FCM_API_KEY`, `FCM_SENDER_ID` and `FCM_SERVICE_ACCOUNT_JSON`. After that the settings page owns them and the variables are ignored, so edit the page, not the environment.

## 5. Check it works

1. **Server config:** `GET <your-server>/api/v1/settings/fcm-config` should return `{"enabled": true, ...}`.
2. **Mobile app:** the app picks up the settings the next time it opens. Enabling push in the app's settings should work without errors.
3. **End to end:** assign yourself a task and confirm a push arrives.

!!! note "Two switches, two questions"
    **Send push notifications** on this page connects the deployment to Firebase. **Mobile notifications**, under **Settings → Platform → Security**, decides whether a notification may reach a phone at all. Push needs both on.

## Self-hosting notes

- **Use your own Firebase project** per deployment. Don't share one across unrelated instances.
- Because configuration is fetched at runtime, you do **not** need to rebuild the mobile app for your Firebase project — the published app reads the config from your backend.
- A *"Could not find google-services.json"* warning during a build can be ignored; runtime configuration is used instead.

## Security notes

- **Never commit** the service-account JSON. It's stored encrypted in your database, and the settings page never shows it back.
- **Rotate** the service-account key periodically (every ~90 days is a good habit): generate a new one and paste it over the old.
- Give the service account only the **Firebase Cloud Messaging** permission it needs.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "FCM not configured" | **Send push notifications** is off, or a field is empty. Fill it in and save. |
| App errors when enabling push | The server's Firebase settings don't match your project — check each field against step 4, and the `/api/v1/settings/fcm-config` endpoint. |
| Push not received | Invalid credentials, the device token wasn't registered, the user disabled the category, or the `project_id` doesn't match — check backend logs and the user's notification settings. |

## Related

- [Configuration](configuration.md) · [Email](email.md)
- [Notifications](../guides/notifications.md) — the user's view.
