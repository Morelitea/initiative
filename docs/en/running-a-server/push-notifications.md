---
icon: lucide/bell-ring
---

# Push notifications (Firebase)

Mobile push notifications are delivered through **Firebase Cloud Messaging (FCM)**. This is optional — Initiative works without it, and in-app and email notifications don't need it. Set it up only if you want alerts pushed to the mobile apps.

Initiative uses **runtime configuration**: you set a few environment variables and the mobile app fetches what it needs from your server. You do **not** need to commit a `google-services.json` file into the app.

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

## 4. Set the environment variables

Add these to your backend environment (for example, your `docker-compose.yml` or `.env`):

```bash
FCM_ENABLED=true
FCM_PROJECT_ID=your-project-id
FCM_APPLICATION_ID=1:123456789:android:abcdef123456
FCM_API_KEY=AIzaSy...
FCM_SENDER_ID=123456789
FCM_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"your-project-id", ... }'
```

Where to find each value:

| Variable | From `google-services.json` | Or in the Firebase console |
|---|---|---|
| `FCM_PROJECT_ID` | `project_info.project_id` | Project Settings → General → Project ID |
| `FCM_SENDER_ID` | `project_info.project_number` | Project Settings → Cloud Messaging → Sender ID |
| `FCM_APPLICATION_ID` | `client[0].client_info.mobilesdk_app_id` | Project Settings → General → Your Apps → App ID |
| `FCM_API_KEY` | `client[0].api_key[0].current_key` | Project Settings → General → Web API Key |

For `FCM_SERVICE_ACCOUNT_JSON`, paste the **entire contents** of the service-account key file you downloaded, minified onto one line, wrapped in single quotes.

## 5. Restart and verify

Restart the backend, then check:

1. **Server config:** `GET <your-server>/api/v1/settings/fcm-config` should return `{"enabled": true, ...}`.
2. **Mobile app:** enabling push in the app's settings should work without errors.
3. **End to end:** assign yourself a task and confirm a push arrives.

## Self-hosting notes

- **Use your own Firebase project** per deployment. Don't share one across unrelated instances.
- Because configuration is fetched at runtime, you do **not** need to rebuild the mobile app for your Firebase project — the published app reads the config from your backend.
- A *"Could not find google-services.json"* warning during a build can be ignored; runtime configuration is used instead.

## Security notes

- **Never commit** the service-account JSON. Keep it in environment variables or a secret store.
- **Rotate** the service-account key periodically (every ~90 days is a good habit).
- Give the service account only the **Firebase Cloud Messaging** permission it needs.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "FCM not configured" | `FCM_ENABLED` is `false` or variables are missing — set them and restart. |
| App errors when enabling push | Backend FCM config invalid or unreachable — check the variables and the `/api/v1/settings/fcm-config` endpoint. |
| Push not received | Invalid credentials, the device token wasn't registered, the user disabled the category, or the `project_id` doesn't match — check backend logs and the user's notification settings. |

## Related

- [Configuration](configuration.md) · [Email](email.md)
- [Notifications](../guides/notifications.md) — the user's view.
