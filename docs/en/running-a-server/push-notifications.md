---
icon: lucide/bell-ring
---

# Push notifications

Push is optional. Initiative works fine without it, and in-app and email notifications don't need it. Turn it on if you want alerts to land on people's phones.

## The short version

Go to **Settings → Platform → Push notifications**, as the [owner](platform-roles.md), turn on **Send push notifications**, and save. That's it. Leave every other field empty.

With no Firebase service account saved, your server sends pushes through **BeyondersStudio's push relay**, which holds the app's credentials with Apple and Google so you don't have to. The app on people's phones picks it up the next time it opens. Nothing to restart, nothing to rebuild, no Firebase console.

| Phone | Goes through |
|---|---|
| **iPhone** | The relay, always. Apple only accepts pushes for the app signed with BeyondersStudio's key, and nobody else can hold that key. |
| **Android**, no service account saved | The relay. |
| **Android**, with your own service account | Your Firebase project, directly. The relay never sees it. |

Nothing contacts the relay until you switch push on.

### How a phone is reached through the relay

Apple and Google address a phone by a **device token**. With the relay in the middle, your server never holds one:

1. **Your server registers with the relay**, once: the first time the app asks it for its push settings, or the first push it sends, whichever comes first. It sends its address's host name, gets back an id and a key, and keeps them encrypted in your database. The id is public and your server hands it to the app; the key stays on your server.
2. **The phone trades its token for a handle.** The app sends its device token straight to the relay, along with your server's id, and gets back a **handle**: an opaque string that reaches this phone, for your server only. The relay's address is built into the app, so a server can't redirect where tokens go.
3. **Your server is told the handle**, never the token, and sends to it like any other. The relay looks the handle up, checks it belongs to your server, and passes the message to Apple or Google.

A handle is useless to anyone but the server it was issued for. When someone signs out, or points the app at a different server, the app deletes its handle at the relay and withdraws it from your server. If the relay says a handle is gone (the app was uninstalled, or Apple or Google retired the token), your server forgets it.

| Platform | What your server stores |
|---|---|
| **iPhone** | A relay handle. |
| **Android**, no service account saved | A relay handle. |
| **Android**, with your own service account | The phone's own Firebase token. The relay isn't involved. |

### What the relay sees

The relay learns **which server a device belongs to, and when it gets a notification**. The notification's title and text pass through it to Apple or Google and are never stored or logged. It only forwards a short list of fields (title, text, the in-app link, the Android channel, a badge count), so nothing your server sends can make a phone open a web page or download an image.

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

1. **Server config:** `GET <your-server>/api/v1/settings/fcm-config` should return `{"enabled": true, ...}` with a `push_relay_server_id` beginning `srv_`. Without a service account, the Firebase fields it shows are the relay's and `android_via_relay` is `true`.
2. **Mobile app:** the app picks up the settings the next time it opens. Enabling push in the app's settings should work without errors.
3. **End to end:** assign yourself a task and confirm a push arrives.

!!! note "Two switches, two questions"
    **Send push notifications** on this page turns push on for the deployment. **Phone and desktop notifications**, under **Settings → Platform → Security**, decides whether a notification may leave the app for a phone or the desktop app at all. Push needs both on.

## If you self-host

- **There's nothing to configure for the relay.** Turning push on is the whole of it: your server registers itself, and the app does the rest. You don't need an account with BeyondersStudio, and no address of yours has to be reachable from the internet (the relay never calls your server; your server calls it).
- **Your server needs to reach `https://push-relay.beyonders.studio`** outbound, and phones need to reach it too. If your firewall only lets your server out to an allow-list, add it.
- **Changing how Android is sent sorts itself out.** Add or remove a service account and the tokens your server has stop matching; it drops them without sending anything, and each phone registers the right kind the next time the app opens.
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
| "Push relay refused this server" | The relay has suspended this server. Get in touch with BeyondersStudio. |
| `push_relay_server_id` is `null` in `fcm-config` | The server couldn't register with the relay yet. Check it can reach `https://push-relay.beyonders.studio`; it tries again a few minutes later. Phones register once it has an id. |
| App errors when enabling push | The server's Firebase settings don't match your project — check each field against step 4, and the `/api/v1/settings/fcm-config` endpoint. |
| Push not received | Invalid credentials, the device token wasn't registered, the user disabled the category, or the `project_id` doesn't match — check backend logs and the user's notification settings. |

## Related

- [Configuration](configuration.md) · [Email](email.md)
- [Notifications](../guides/notifications.md) — the user's view.
