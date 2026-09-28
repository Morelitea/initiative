---
icon: lucide/hammer
---

# Building your own image

This page is for people who build Initiative from source: a fork, a patched image, a copy with the logo swapped for a picture of the committee's cat. Running the published image? Close this tab with a clear conscience. It already does all of this for you.

!!! warning "Self-built images are not supported"
    We support the published image, online or air-gapped. A build of your own is yours to run and yours to fix. This page covers the one thing that doesn't work until you set it up: app updates.

## How the app decides to update

The mobile app updates itself from the server it's connected to. It only installs an update that's signed with a key it trusts, and the published app trusts Initiative's release key.

Your image doesn't have that key, so its updates arrive unsigned. The app stays on the version it has and says so, once. Nothing breaks. It just doesn't move.

To update from your own server, you need your own key in two places: the app, and the image.

## 1. Make a key

```bash
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out ota-signing-key.pem
openssl pkey -in ota-signing-key.pem -pubout -outform DER | openssl base64 -A > ota-public-key.txt
```

`ota-signing-key.pem` is the private half. Keep it out of the repository, and keep it somewhere you'll find it again: without it, your app takes no further updates until everybody reinstalls. `ota-public-key.txt` is fine to share.

## 2. Build your app with it

The app only trusts keys it was built with, so the published app will never take your updates. Build your own:

```bash
cd frontend
VITE_OTA_DEV_KEY="$(cat ../ota-public-key.txt)" pnpm build:capacitor
npx cap sync android
```

Then build and sign the APK the way you would any Android app. An APK signed with your own Android key can't install over the published one, so uninstall that first.

## 3. Build your image with it

The image needs the public key as well. The update it serves becomes the app on the phone, and that copy has to go on trusting your key for the update after. The private key goes in as a build secret, so it stays out of the image.

```bash
docker build \
  --build-arg VITE_OTA_DEV_KEY="$(cat ota-public-key.txt)" \
  --secret id=ota_signing_key,src=ota-signing-key.pem \
  -t my-initiative .
```

Check the build log. `sign-ota: signed <version>` means it worked. `sign-ota: no signing key; this build's bundle is unsigned` means the secret never arrived.

??? techspec "What gets signed"
    `frontend/scripts/sign-ota.mjs` signs a short JSON statement (the bundle's version, its SHA-256, and the oldest native app it runs on, from `MIN_NATIVE_VERSION`) with ECDSA P-256 over SHA-256. `/api/v1/native/bundle/manifest` serves the statement and its signature. The app checks them against its built-in keys and `VITE_OTA_DEV_KEY` before downloading anything, then checks the download against the statement's digest.
