"""Version utilities for reading application version."""

from pathlib import Path


def get_version() -> str:
    """Read version from VERSION file at project root."""
    # Try Docker path first: /app/app/core/version.py -> /app/VERSION
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    # Fall back to development path: backend/app/core/version.py -> ../../../../VERSION
    version_file = Path(__file__).parent.parent.parent.parent / "VERSION"
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        return "0.0.0"


def get_min_native_version() -> str:
    """Read the minimum native app version from the MIN_NATIVE_VERSION file at project root.

    This is the semver of the release in which the native shell last changed (Capacitor
    plugins or config). The OTA flow refuses a web bundle whose ``minNativeVersion`` exceeds
    the installed native app version, prompting a store/APK update instead — because a newer
    web bundle may call a native API the older shell lacks. Resolution mirrors ``get_version``
    (Docker path first).
    """
    # Try Docker path first: /app/app/core/version.py -> /app/MIN_NATIVE_VERSION
    min_version_file = Path(__file__).parent.parent.parent / "MIN_NATIVE_VERSION"
    if not min_version_file.exists():
        # Fall back to development path: -> repo_root/MIN_NATIVE_VERSION
        min_version_file = (
            Path(__file__).parent.parent.parent.parent / "MIN_NATIVE_VERSION"
        )
    try:
        return min_version_file.read_text().strip()
    except FileNotFoundError:
        return "0.0.0"


__version__ = get_version()
