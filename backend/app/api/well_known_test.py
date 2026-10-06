"""The association files a phone reads before an app may run a passkey
ceremony for this deployment."""

from __future__ import annotations

from app.core import native_apps, version
from app.core.config import settings


async def test_asset_links_name_the_apps_this_image_vouches_for(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_URL", "https://initiative.example.org")
    monkeypatch.setattr(version, "is_dev_image", lambda: False)

    resp = await client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.json() == [
        {
            "relation": ["delegate_permission/common.get_login_creds"],
            "target": {
                "namespace": "android_app",
                "package_name": native_apps.ANDROID_PACKAGE,
                "sha256_cert_fingerprints": list(native_apps.ANDROID_FINGERPRINTS),
            },
        }
    ]

    monkeypatch.setattr(version, "is_dev_image", lambda: True)
    resp = await client.get("/.well-known/assetlinks.json")
    assert [s["target"]["package_name"] for s in resp.json()] == [
        native_apps.ANDROID_PACKAGE,
        native_apps.ANDROID_DEV_PACKAGE,
    ]

    # An address no passkey can be bound to vouches for nobody.
    monkeypatch.setattr(settings, "APP_URL", "https://192.168.1.10")
    assert (await client.get("/.well-known/assetlinks.json")).status_code == 404


async def test_apple_association_waits_for_an_ios_app(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_URL", "https://initiative.example.org")
    path = "/.well-known/apple-app-site-association"

    monkeypatch.setattr(native_apps, "IOS_APP_IDS", ())
    assert (await client.get(path)).status_code == 404

    monkeypatch.setattr(native_apps, "IOS_APP_IDS", ("TEAMID.example.app",))
    resp = await client.get(path)
    assert resp.status_code == 200
    assert resp.json() == {"webcredentials": {"apps": ["TEAMID.example.app"]}}

    monkeypatch.setattr(settings, "APP_URL", "http://intranet.local")
    assert (await client.get(path)).status_code == 404
