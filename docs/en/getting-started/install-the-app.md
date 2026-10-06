---
icon: lucide/smartphone
---

# Installing the app

Initiative runs in a browser, and using it that way forever is a completely respectable life choice. But you can also give it its own icon, its own window, and — on a phone — notifications that arrive when you aren't looking.

A few ways to do that. None takes longer than finding the charger.

## Install it from the browser

Initiative is a **progressive web app**, which is a dreadful name for a nice thing: the website installs itself. Same app, same account, no store, no download.

| Where you are | What to tap |
|---|---|
| **iPhone or iPad (Safari)** | Share button, then **Add to Home Screen** |
| **Android (Chrome)** | The ⋮ menu, then **Install app** or **Add to Home screen** |
| **Chrome or Edge on a computer** | The install icon at the right-hand end of the address bar |
| **Firefox on Windows** | **Add tab to taskbar**, in that same corner of the address bar |

Firefox on Linux has the same button, once `browser.taskbarTabs.enabled` is switched on in `about:config`. On a Mac, Safari is the one that does this — Firefox there keeps Initiative in a tab, which works perfectly well and simply looks less like an app.

After that it opens in its own window with no browser furniture around it, stays signed in, and will still show you the projects and tasks you looked at recently when the train goes into a tunnel. Changing anything still wants a connection.

!!! warning "The install option isn't there"
    Browsers only offer this over a secure `https://` address. If your group's Initiative is on plain `http://`, the option quietly won't appear — nothing is broken and you haven't missed a setting. It's a question for whoever set the server up.

## The phone apps

There are proper apps for iPhone and Android as well. Same Initiative inside, but they do the thing a browser tab can't: **push notifications**, arriving on your phone while the app is shut. If whoever runs your server has [set that up](../running-a-server/push-notifications.md), this is the version you want.

| Phone | Where to get it |
|---|---|
| **iPhone or iPad** | The App Store. Search for **Initiative**, by Beyonders Studio. |
| **Android** | Google Play, same search. Or [without Google Play](#android-without-google-play), straight from the project. |

The first launch asks which Initiative it's talking to, because there are a lot of them and it can't guess. See [the mobile app](signing-in.md#the-mobile-app).

The apps only talk to servers on a secure `https://` address. A server on plain `http://` won't connect from the app, though the browser still reaches it. Same answer as above: a question for whoever set the server up.

### Android, without Google Play

[![Get it on Obtainium](https://raw.githubusercontent.com/ImranR98/Obtainium/main/assets/graphics/badge_obtainium.png){ width="240" }](https://apps.obtainium.imranr.dev/redirect?r=obtainium%3A%2F%2Fadd%2Fhttps%3A%2F%2Fgithub.com%2Fbeyonders-studio%2Finitiative)

[Obtainium](https://github.com/ImranR98/Obtainium) is a free app that watches a project's releases and keeps you updated from them. Install Obtainium first, then tap that button and it fills in the rest, including working back to the most recent release that actually carries an app. Doing it by hand instead: take the newest [release](https://github.com/beyonders-studio/initiative/releases) with an `.apk` on it. That often isn't the top one: the app is only rebuilt when it changes, and the releases in between are web-only.

Either way Android will check that you meant to install something from outside the Play Store. You did. Allow it for whichever app is doing the installing.

### It keeps itself current

When your community's server moves to a new version, the app fetches the matching update in the background and offers to reload. Most of the time, that's the whole story.

Every so often a release changes the app itself rather than what runs inside it. Then the app says so and sends you back to wherever it came from: the App Store, Google Play, or a new APK. On iPhone, each feature release arrives that way too, and the fixes in between come over the air.

### New phone, same app

Restore your old phone's backup onto a new one and the app comes back with your server address and settings where you left them. It asks you to sign in again, because your sign-in and your message keys belong to the old phone and don't travel in the backup.

??? techspec "How the over-the-air update works"
    Each Docker image ships the Capacitor web bundle that matches its version, served from `/api/v1/native/bundle/`, along with a statement of that bundle (its version, checksum and the oldest app it runs on) signed with Initiative's release key. On launch the app checks the signature against the keys it was built with, compares the signed version with the one it's running, downloads the difference, verifies its checksum, and swaps it in behind the splash screen. A bundle without a valid signature is left alone and the app stays on the version it has.

    It never goes back past the version the installed app shipped with. A server older than that leaves the app on what it already runs, so an old server can't swap in a bundle from before the app was built.

    An over-the-air update can only replace web assets, never native code. Each bundle therefore declares a `minNativeVersion`, and the app refuses any bundle that needs a newer shell than the installed APK — prompting for a store or APK update instead. On iPhone a bundle from another minor release is refused the same way, so feature releases come through the App Store. Release CI rebuilds the APK only when that floor moves, so most releases attach none at all. An updater watching the releases falls back to the last one that did — which is the build you want, because it is still the shell this bundle runs on. Re-attaching that same APK to later releases would be worse than attaching nothing: an updater reads the release, not the file, so it would see a new version each time and reinstall the app you already have.

## The desktop app

There's an app for Windows, Mac and Linux as well. Same Initiative, in its own window, and it signs in as one of your devices, the way the phone apps do.

Get it from the **Download** page on your community's Initiative, which picks the right file for your computer. Or take it from the newest [release](https://github.com/beyonders-studio/initiative/releases) that has one: the `.exe` for Windows, the `.dmg` for a Mac, the `.deb` for Debian and Ubuntu.

!!! note "Your computer will ask whether you meant it"
    The installers aren't signed with a publisher's certificate yet, so Windows and macOS stop and check. On Windows, choose **More info**, then **Run anyway**. On a Mac, open it once, then go to **System Settings › Privacy & Security** and choose **Open Anyway**.

The first launch asks which Initiative it's talking to, like the phone. It keeps itself current the same way too.

Once in a while a release changes the app itself, and then it says so. On Windows and Linux it can fetch and install the new app for you: choose **Update now**, and leave **Always update automatically** ticked if you'd rather not be asked again. After that it downloads the next one on its own and only asks you to restart. Change your mind with **Update the app automatically**, under **My Settings › Preferences**. A Mac gets a **Download** button instead, until the app is signed for macOS.

Notifications pop up on your computer whenever Initiative's window isn't the one in front, and clicking one takes you to it. The app's icon carries your unread count.

Close the window on Windows or Linux and Initiative carries on in the tray, so notifications keep reaching you; **Quit** is on the tray icon. A Mac keeps it in the dock, as Macs do. **My Settings › Preferences** has the switches: **Keep running when the window closes** and **Open when the computer starts**.

## Next

Now go and find where everything lives: [take the quick tour](a-quick-tour.md).
