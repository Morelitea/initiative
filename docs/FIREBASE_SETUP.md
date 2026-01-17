# Firebase Setup for Push Notifications

## Overview

Push notifications require Firebase Cloud Messaging (FCM) configuration. This guide explains how to set up Firebase for both development and production deployments.

## Why google-services.json is Required

The Capacitor Push Notifications plugin uses Firebase Cloud Messaging on Android. Firebase requires `google-services.json` to initialize properly at the native level. Without this file, the app will crash when attempting to use push notifications.

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

### 3. Download google-services.json

1. Download the `google-services.json` file provided by Firebase
2. Place it in: `frontend/android/app/google-services.json`

**Important**: Do NOT commit this file to git if it contains production credentials. Add it to `.gitignore` if needed.

### 4. Configure Backend

The backend needs Firebase service account credentials to send push notifications.

#### 4.1 Generate Service Account Key

1. In Firebase Console, go to Project Settings → Service Accounts
2. Click "Generate New Private Key"
3. Save the JSON file securely (do NOT commit to git)

#### 4.2 Set Environment Variables

Add these to `backend/.env`:

```bash
# Push Notifications (Firebase Cloud Messaging)
FCM_ENABLED=true
FCM_PROJECT_ID=your-project-id
FCM_APPLICATION_ID=1:123456789:android:abcdef123456  # From google-services.json
FCM_API_KEY=AIzaSy...  # From Firebase Console → Project Settings → Web API Key
FCM_SENDER_ID=123456789  # From Firebase Console → Cloud Messaging → Sender ID
FCM_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"your-project-id",...}'  # Full service account JSON as string
```

#### 4.3 Find Configuration Values

**From google-services.json:**
- `FCM_PROJECT_ID`: `project_info.project_id`
- `FCM_APPLICATION_ID`: `client[0].client_info.mobilesdk_app_id`
- `FCM_SENDER_ID`: `project_info.project_number`

**From Firebase Console:**
- Go to Project Settings → General
- **API Key**: Listed under "Web API Key"

**Service Account JSON:**
- Copy the entire contents of the service account key file
- Minify it (remove newlines and extra spaces)
- Set as environment variable (wrap in single quotes)

### 5. Rebuild the App

After adding google-services.json:

```bash
cd frontend
npx cap sync android
pnpm build:capacitor
npx cap run android
```

The Google Services plugin will now be applied during the build.

## Verification

1. **Build Logs**: Check that the build log shows "google-services plugin applied"
2. **Backend Config**: Visit `http://your-backend/api/v1/settings/fcm-config` - should return `{"enabled": true, ...}`
3. **Mobile App**: Enable push notifications in settings - should no longer crash
4. **Test Notification**: Create a task assignment and verify push notification is received

## Development vs Production

### Development Setup

For local development, you can use a single Firebase project with:
- Development google-services.json in the app
- Development service account in backend .env

### Production Setup

For self-hosted production deployments:

1. **Each instance should use their own Firebase project**
2. **Mobile App**: Each user rebuilds the APK with their google-services.json
3. **Backend**: Each user configures their own FCM environment variables

### Docker Deployment

When deploying via Docker:

**Option 1: Build custom image with google-services.json**
```dockerfile
# In frontend/android/app/
COPY google-services.json /app/frontend/android/app/
```

**Option 2: Mount as volume** (if using prebuilt APK)
- Build APK locally with google-services.json
- Deploy the prebuilt APK via Docker volume mount

## Troubleshooting

### App crashes when enabling push notifications

**Cause**: Missing or invalid google-services.json

**Solution**:
1. Verify google-services.json exists at `frontend/android/app/google-services.json`
2. Verify package name matches: `com.morelitea.initiative`
3. Run `npx cap sync android` to apply changes
4. Rebuild the app

### Backend returns "FCM not configured"

**Cause**: FCM_ENABLED=false or missing service account

**Solution**:
1. Set `FCM_ENABLED=true` in backend/.env
2. Set `FCM_SERVICE_ACCOUNT_JSON` with valid service account
3. Restart backend

### Push notifications not received

**Possible causes**:
1. Backend FCM credentials invalid → Check backend logs
2. Token not registered → Check database `push_tokens` table
3. User preferences disabled → Check user notification settings
4. Invalid push token → FCM returns 404/410, token should be deleted
5. Firebase project misconfigured → Verify project_id matches

## Security Notes

- **Never commit service account JSON to git** - use environment variables
- **Never commit production google-services.json** - add to .gitignore if sensitive
- **Rotate service account keys periodically** - every 90 days recommended
- **Use separate Firebase projects** for development and production
- **Limit service account permissions** - only needs "Firebase Cloud Messaging API Service Agent"

## Alternative: Runtime Configuration (Future)

The original plan mentioned runtime configuration without google-services.json. This approach is technically possible but requires:

1. Custom native code to initialize Firebase programmatically
2. Fetching config from backend API at runtime
3. May not be supported by standard Capacitor plugins

For now, using google-services.json is the standard and recommended approach.

## Reference

- [Firebase Console](https://console.firebase.google.com/)
- [Capacitor Push Notifications Plugin](https://capacitorjs.com/docs/apis/push-notifications)
- [Firebase Cloud Messaging Documentation](https://firebase.google.com/docs/cloud-messaging)
- [google-services Plugin](https://developers.google.com/android/guides/google-services-plugin)
