"""The association files a phone reads before an app may run a passkey
ceremony for this deployment.

Both are served only when the deployment's address can carry a passkey at all
(``site_refusal``): a phone would refuse an IP address or plain http anyway.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core import native_apps
from app.services.auth import passkeys as passkey_service

router = APIRouter(prefix="/.well-known", include_in_schema=False)


@router.get("/assetlinks.json")
async def android_asset_links() -> JSONResponse:
    """The Android apps that may sign in to this deployment with a passkey."""
    if passkey_service.site_refusal() is not None:
        raise HTTPException(status_code=404)
    return JSONResponse(
        [
            {
                "relation": ["delegate_permission/common.get_login_creds"],
                "target": {
                    "namespace": "android_app",
                    "package_name": package,
                    "sha256_cert_fingerprints": list(fingerprints),
                },
            }
            for package, fingerprints in native_apps.android_apps()
        ]
    )


@router.get("/apple-app-site-association")
async def apple_app_site_association() -> JSONResponse:
    """The iOS apps that may sign in to this deployment with a passkey."""
    if passkey_service.site_refusal() is not None or not native_apps.IOS_APP_IDS:
        raise HTTPException(status_code=404)
    return JSONResponse({"webcredentials": {"apps": list(native_apps.IOS_APP_IDS)}})
