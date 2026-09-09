---
icon: lucide/smartphone
---

# Installing the app

Initiative runs in a browser, and using it that way forever is a completely respectable life choice. But you can also give it its own icon, its own window, and — on Android — notifications that arrive when you aren't looking.

Two ways to do that. Neither takes longer than finding the charger.

## Install it from the browser

Initiative is a **progressive web app**, which is a dreadful name for a nice thing: the website installs itself. Same app, same account, no store, no download.

| Where you are | What to tap |
|---|---|
| **iPhone or iPad (Safari)** | Share button, then **Add to Home Screen** |
| **Android (Chrome)** | The ⋮ menu, then **Install app** or **Add to Home screen** |
| **Chrome or Edge on a computer** | The install icon at the right-hand end of the address bar |
| **Firefox on Windows** | **Add tab to taskbar**, in that same corner of the address bar |

Firefox on Linux has the same button, once `browser.taskbarTabs.enabled` is switched on in `about:config`. On a Mac, Safari is the one that does this — Firefox there still keeps Initiative in a tab, which works perfectly well and simply looks less like an app.

After that it opens in its own window with no browser furniture around it, stays signed in, and will still show you the projects and tasks you looked at recently when the train goes into a tunnel. Changing anything still wants a connection.

!!! warning "The install option isn't there"
    Browsers only offer this over a secure `https://` address. If your group's Initiative is on plain `http://`, the option quietly won't appear — nothing is broken and you haven't missed a setting. It's a question for whoever set the server up.

## The Android app

There's a proper Android app as well. Same Initiative inside, but it can do the thing a browser tab can't: **push notifications**, arriving on your phone while the app is shut. If your community's administrator has [set that up](../admin/push-notifications.md), this is the version you want.

[![Get it on Obtainium](https://raw.githubusercontent.com/ImranR98/Obtainium/main/assets/graphics/badge_obtainium.png){ width="240" }](https://apps.obtainium.imranr.dev/redirect?r=obtainium%3A%2F%2Fadd%2Fhttps%3A%2F%2Fgithub.com%2FMorelitea%2Finitiative)

[Obtainium](https://github.com/ImranR98/Obtainium) is a free app that watches a project's releases and keeps you updated from them. Install Obtainium first, then tap that button and it fills in the rest, including working back to the most recent release that actually carries an app. Doing it by hand instead: take the newest [release](https://github.com/Morelitea/initiative/releases) with an `.apk` on it. That often isn't the top one: the app is only rebuilt when it changes, and the releases in between are web-only.

Either way Android will check that you meant to install something from outside the Play Store. You did. Allow it for whichever app is doing the installing.

The first launch asks which Initiative it's talking to, because there are a lot of them and it can't guess. See [the mobile app](signing-in.md#the-mobile-app).

### It keeps itself current

When your community's server moves to a new version, the app fetches the matching update in the background and offers to reload. You don't reinstall anything and you don't visit a store.

Every so often a release changes the app's native shell rather than the web part, and then it'll say so and point you at a new APK. That's the only time it needs you.

??? techspec "How the over-the-air update works"
    Each Docker image ships the Capacitor web bundle that matches its version, served from `/api/v1/native/bundle/`. On launch the app compares the served version with the one it's running, downloads the difference, verifies its checksum, and swaps it in behind the splash screen.

    An over-the-air update can only replace web assets, never native code. Each bundle therefore declares a `minNativeVersion`, and the app refuses any bundle that needs a newer shell than the installed APK — prompting for a store or APK update instead. Release CI rebuilds the APK only when that floor moves, so most releases attach none at all. An updater watching the releases falls back to the last one that did — which is the build you want, because it is still the shell this bundle runs on. Re-attaching that same APK to later releases would be worse than attaching nothing: an updater reads the release, not the file, so it would see a new version each time and reinstall the app you already have.

## On iPhone

The home-screen install in the table above is the iPhone version — the icon, the standalone window, all of it. Notifications reach you by email and in the app's own bell.

## Next

Now go and find where everything lives: [take the quick tour](a-quick-tour.md).
