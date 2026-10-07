"""The project's own apps, as a deployment vouches for them.

A phone app may run a passkey ceremony for a deployment only when the
deployment names it: Android reads ``/.well-known/assetlinks.json`` and iOS
reads ``/.well-known/apple-app-site-association``. These identities are the
project's, not an operator's, for the same reason as the update keys in
``frontend/src/lib/otaTrust.ts``, so they are compiled in rather than
configured.

The dev app is named only by dev images, the way only the dev app trusts the
dev update key.
"""

from __future__ import annotations

import base64

from app.core import version

#: The Android app, and the SHA-256 fingerprints of the certificates it is
#: signed with: the APK the project publishes, and Google Play's beside it once
#: the app is set up there.
ANDROID_PACKAGE = "studio.beyonders.initiative"
ANDROID_FINGERPRINTS: tuple[str, ...] = (
    "72:FB:17:1C:A1:8A:CA:30:A6:99:81:B8:84:0F:E1:6B:03:51:7C:E4:AF:81:96:CF:4E:8B:91:7B:BB:DB:1B:BF",
)

#: Initiative Dev, built from ``dev`` and signed with the dev keystore.
ANDROID_DEV_PACKAGE = "studio.beyonders.initiative.dev"
ANDROID_DEV_FINGERPRINTS: tuple[str, ...] = (
    "42:9A:61:26:F7:A6:5F:9F:93:A7:17:36:C0:93:E2:61:BC:F4:09:7B:0A:78:74:B9:C6:0C:86:89:8C:FE:17:F8",
)

#: ``<Team ID>.<bundle id>`` for each iOS app (``studio.beyonders.initiative``).
#: Empty until the App Store account exists; the association route answers 404
#: while it is. An iPhone reads the file only for the domains the app's own
#: entitlements name (``initiativetasks.com`` and ``demo.initiativetasks.com``),
#: so serving it from any other deployment is harmless.
IOS_APP_IDS: tuple[str, ...] = ()


def android_apps() -> list[tuple[str, tuple[str, ...]]]:
    """Each Android app this image vouches for, with its fingerprints."""
    apps = [(ANDROID_PACKAGE, ANDROID_FINGERPRINTS)]
    if version.is_dev_image():
        apps.append((ANDROID_DEV_PACKAGE, ANDROID_DEV_FINGERPRINTS))
    return apps


def android_origins() -> list[str]:
    """The origins Android reports for a ceremony one of these apps ran: the
    unpadded base64url SHA-256 of its signing certificate, rather than an
    address."""
    return [
        "android:apk-key-hash:"
        + base64.urlsafe_b64encode(bytes.fromhex(fingerprint.replace(":", "")))
        .rstrip(b"=")
        .decode()
        for _, fingerprints in android_apps()
        for fingerprint in fingerprints
    ]
