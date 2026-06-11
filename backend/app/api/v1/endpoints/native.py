"""Native (Capacitor) over-the-air bundle endpoints.

Each Docker image bundles the Capacitor-flavored web build (a zip with ``index.html`` at
its root) under ``/app/ota`` so the native app can download the web bundle that matches the
backend it is talking to. The native app polls ``/native/bundle/manifest`` and, when the
served version differs from the bundle it is running, downloads ``/native/bundle/download``
and swaps it in via ``@capgo/capacitor-updater`` (manual mode).

See ``backend/app/main.py`` for the analogous static/upload ``FileResponse`` patterns.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.messages import NativeMessages
from app.core.version import __version__, get_min_native_version

router = APIRouter()

# Docker layout: /app/app/api/v1/endpoints/native.py -> parents[4] == /app
# The Dockerfile copies the OTA artifacts to /app/ota (see Dockerfile stage 2).
# In a local dev checkout this directory does not exist, so the endpoints 404 — the OTA
# flow is only exercised against a built image.
_OTA_DIR = Path(__file__).resolve().parents[4] / "ota"
_BUNDLE_PATH = _OTA_DIR / "bundle.zip"
_CHECKSUM_PATH = _OTA_DIR / "bundle.sha256"


@router.get("/native/bundle/manifest")
def get_bundle_manifest() -> dict[str, object]:
    """Describe the OTA bundle this backend serves.

    Returns the bundle ``version`` (equal to the app version), a ``url`` the client joins to
    its server origin to download the zip, the ``checksum`` (sha256 hex) the updater verifies,
    and ``minNativeVersion`` — the minimum native app (APK/IPA) version the bundle requires.
    The client refuses the update (and prompts to update from the store) when its installed
    native app version is older.
    """
    if not _BUNDLE_PATH.is_file() or not _CHECKSUM_PATH.is_file():
        raise HTTPException(
            status_code=404, detail=NativeMessages.OTA_BUNDLE_NOT_AVAILABLE
        )
    return {
        "version": __version__,
        "url": f"{settings.API_V1_STR}/native/bundle/download",
        "checksum": _CHECKSUM_PATH.read_text().strip(),
        "minNativeVersion": get_min_native_version(),
    }


@router.get("/native/bundle/download")
def download_bundle() -> FileResponse:
    """Serve the Capacitor web bundle zip (immutable per version)."""
    if not _BUNDLE_PATH.is_file():
        raise HTTPException(
            status_code=404, detail=NativeMessages.OTA_BUNDLE_NOT_AVAILABLE
        )
    return FileResponse(
        _BUNDLE_PATH,
        media_type="application/zip",
        filename=f"initiative-{__version__}.zip",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
