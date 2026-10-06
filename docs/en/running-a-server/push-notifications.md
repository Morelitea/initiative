---
icon: lucide/bell-ring
---

# Push notifications

Push is optional. Initiative works fine without it, and in-app and email notifications don't need it. Turn it on if you want alerts to land on people's phones.

## The short version

Go to **Settings → Platform → Push notifications**, as the [owner](platform-roles.md), turn on **Send push notifications**, and save. That's it. Leave every other field empty.

With no Firebase service account saved, your server sends pushes through **Morelitea's push relay**, which holds the app's credentials with Apple and Google so you don't have to. The app on people's phones picks it up the next time it opens. Nothing to restart, nothing to rebuild, no Firebase console.

| Phone | Goes through |
|---|---|
| **iPhone** | The relay, always. Apple only accepts pushes for the app signed with Morelitea's key, and nobody else can hold that key. |
| **Android**, no service account saved | The relay. |
| **Android**, with your own service account | Your Firebase project, directly. The relay never sees it. |

Nothing contacts the relay until you switch push on.

### What the relay sees

The first push your server sends, it registers itself with the relay: it sends its address's host name, gets back an id and a key, and keeps them encrypted in your database. It does this once.

After that, the relay learns **which server a device belongs to, and when it gets a notification**. The notification's title and text pass through it to Apple or Google and are never stored or logged.

If your server must not talk to anything outside your network, push through any public app (ours included) is off the table. Set up your own Firebase project below for Android; an iPhone app would have to be built and signed under your own Apple account.

## Your own Firebase project (optional)

Only if you'd rather Android pushes went straight through your own Firebase project. You enter everything on the same settings page, and the mobile app fetches what it needs from your server. You do **not** need to commit a `google-services.json` file into the app.

### 1. Create a Firebase project

1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** (or pick an existing one) and follow the prompts.

### 2. Register an Android app

1. In the Firebase console, add an **Android** app.
2. Use the package name **`studio.beyonders.initiative`** (it must match exactly).
3. Register the app and download the generated `google-services.json` — you'll read a few values out of it, not commit it.

### 3. Generate a service-account key

1. In **Project Settings → Service Accounts**, click **Generate New Private Key**.
2. Save the JSON file somewhere safe. **Never commit it to source control.**

### 4. Fill in the settings

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

## Check it works

1. **Server config:** `GET <your-server>/api/v1/settings/fcm-config` should return `{"enabled": true, ...}`. Without a service account, the Firebase fields it shows are the relay's.
2. **Mobile app:** the app picks up the settings the next time it opens. Enabling push in the app's settings should work without errors.
3. **End to end:** assign yourself a task and confirm a push arrives.

!!! note "Two switches, two questions"
    **Send push notifications** on this page turns push on for the deployment. **Phone and desktop notifications**, under **Settings → Platform → Security**, decides whether a notification may leave the app for a phone or the desktop app at all. Push needs both on.

## Self-hosting notes

- **If you use your own Firebase project**, use one per deployment. Don't share one across unrelated instances.
- Because configuration is fetched at runtime, you do **not** need to rebuild the mobile app for your Firebase project — the published app reads the config from your backend.
- A *"Could not find google-services.json"* warning during a build can be ignored; runtime configuration is used instead.

## Security notes

- **Never commit** the service-account JSON. It's stored encrypted in your database, and the settings page never shows it back.
- **Rotate** the service-account key periodically (every ~90 days is a good habit): generate a new one and paste it over the old.
- Give the service account only the **Firebase Cloud Messaging** permission it needs.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "FCM not configured" | **Send push notifications** is off. Turn it on and save. |
| "Push relay credentials unavailable" in the logs | The server couldn't register with the relay (it can't reach it, or the relay is busy). It tries again a few minutes later on its own. |
| "Push relay refused this server" | The relay has suspended this server. Get in touch with Morelitea. |
| App errors when enabling push | The server's Firebase settings don't match your project — check each field against step 4, and the `/api/v1/settings/fcm-config` endpoint. |
| Push not received | Invalid credentials, the device token wasn't registered, the user disabled the category, or the `project_id` doesn't match — check backend logs and the user's notification settings. |

## Related

- [Configuration](configuration.md) · [Email](email.md)
- [Notifications](../guides/notifications.md) — the user's view.
