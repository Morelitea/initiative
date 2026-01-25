# Firebase Setup for Push Notifications

## Overview

Push notifications require Firebase Cloud Messaging (FCM) configuration. Initiative uses **runtime configuration** - you only need to set environment variables, no `google-services.json` file is required in the source code.

## Setup Steps

### 1. Create a Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click "Add project" or select an existing project
3. Follow the prompts to create your project
4. Enable Google Analytics (optional but recommended)

### 2. Register Your Android App

1. In the Firebase Console, click the Android icon to add an Android app
2. **Package name**: Enter `com.morelitea.initiative` (must match exactly)
3. **App nickname** (optional): "Initiative" or "Initiative Mobile"
4. **Debug signing certificate SHA-1** (optional): Leave blank for now
5. Click "Register app"
6. Download `google-services.json` - you'll extract values from it (see below)

### 3. Generate Service Account Key

1. In Firebase Console, go to Project Settings → Service Accounts
2. Click "Generate New Private Key"
3. Save the JSON file securely (do NOT commit to git)

### 4. Configure Environment Variables

Add these to `backend/.env` (or docker-compose.yml environment variables):

```bash
# Push Notifications (Firebase Cloud Messaging)
FCM_ENABLED=true
FCM_PROJECT_ID=your-project-id
FCM_APPLICATION_ID=1:123456789:android:abcdef123456
FCM_API_KEY=AIzaSy...
FCM_SENDER_ID=123456789
FCM_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"your-project-id",...}'
```

### 5. Finding Configuration Values

#### From google-services.json

If you downloaded `google-services.json`, you can find these values:

| Environment Variable | JSON Path                                | Example Value                           |
| -------------------- | ---------------------------------------- | --------------------------------------- |
| `FCM_PROJECT_ID`     | `project_info.project_id`                | `"my-app-12345"`                        |
| `FCM_APPLICATION_ID` | `client[0].client_info.mobilesdk_app_id` | `"1:123456789012:android:abc123def456"` |
| `FCM_SENDER_ID`      | `project_info.project_number`            | `"123456789012"`                        |
| `FCM_API_KEY`        | `client[0].api_key[0].current_key`       | `"AIzaSyABC123..."`                     |

Example `google-services.json` structure:

```json
{
  "project_info": {
    "project_number": "123456789012", // ← FCM_SENDER_ID
    "project_id": "my-app-12345" // ← FCM_PROJECT_ID
  },
  "client": [
    {
      "client_info": {
        "mobilesdk_app_id": "1:123456789012:android:abc123def456" // ← FCM_APPLICATION_ID
      },
      "api_key": [
        {
          "current_key": "AIzaSyABC123..." // ← FCM_API_KEY
        }
      ]
    }
  ]
}
```

#### From Firebase Console

Alternatively, find values directly in the Firebase Console:

- **FCM_PROJECT_ID**: Project Settings → General → "Project ID"
- **FCM_API_KEY**: Project Settings → General → "Web API Key"
- **FCM_SENDER_ID**: Project Settings → Cloud Messaging → "Sender ID"
- **FCM_APPLICATION_ID**: Project Settings → General → Your Apps → "App ID"

#### Service Account JSON

For `FCM_SERVICE_ACCOUNT_JSON`:

1. Copy the entire contents of the service account key file you downloaded
2. Minify it (remove newlines and extra spaces)
3. Set as environment variable wrapped in single quotes

```bash
FCM_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"my-app-12345","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"...","client_id":"...","auth_uri":"...","token_uri":"...","auth_provider_x509_cert_url":"...","client_x509_cert_url":"..."}'
```

### 6. Build the App

After configuring environment variables, build the app:

```bash
cd frontend
pnpm build
pnpm cap sync android
```

The app will fetch FCM configuration from the backend at runtime.

## Verification

1. **Backend Config**: Visit `http://your-backend/api/v1/settings/fcm-config` - should return `{"enabled": true, ...}`
2. **Mobile App**: Enable push notifications in settings - should work without crashing
3. **Test Notification**: Create a task assignment and verify push notification is received

## Development vs Production

### Development Setup

For local development:

- Configure FCM environment variables in `backend/.env`
- Build and run the app locally

### Production / Self-Hosted Setup

For self-hosted deployments:

1. **Each instance should use their own Firebase project**
2. **Backend**: Configure FCM environment variables
3. **Mobile App**: Use the published APK (it fetches config from your backend)

No need to rebuild the APK for different Firebase projects - the app fetches configuration at runtime from your backend.

## Troubleshooting

### App crashes when enabling push notifications

**Cause**: Backend FCM configuration invalid or unreachable

**Solution**:

1. Verify all FCM environment variables are set correctly
2. Check backend logs for FCM initialization errors
3. Verify the backend `/api/v1/settings/fcm-config` endpoint returns valid config

### Backend returns "FCM not configured"

**Cause**: `FCM_ENABLED=false` or missing environment variables

**Solution**:

1. Set `FCM_ENABLED=true` in backend/.env
2. Set all required FCM environment variables
3. Restart backend

### Push notifications not received

**Possible causes**:

1. Backend FCM credentials invalid → Check backend logs
2. Token not registered → Check database `push_tokens` table
3. User preferences disabled → Check user notification settings
4. Invalid push token → FCM returns 404/410, token should be deleted
5. Firebase project misconfigured → Verify project_id matches

### "Could not find google-services.json" warning

This warning can be ignored. The app uses runtime configuration and does not require `google-services.json`.

## Security Notes

- **Never commit service account JSON to git** - use environment variables
- **Rotate service account keys periodically** - every 90 days recommended
- **Use separate Firebase projects** for development and production
- **Limit service account permissions** - only needs "Firebase Cloud Messaging API Service Agent"

## Reference

- [Firebase Console](https://console.firebase.google.com/)
- [Capacitor Push Notifications Plugin](https://capacitorjs.com/docs/apis/push-notifications)
- [Firebase Cloud Messaging Documentation](https://firebase.google.com/docs/cloud-messaging)
