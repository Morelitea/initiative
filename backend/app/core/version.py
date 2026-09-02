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


def _parts(version: str) -> tuple[int, int, int]:
    """``"0.64.3"`` -> ``(0, 64, 3)``. Anything unparseable sorts as ``0.0.0``.

    Tolerant on purpose: a version read back from a database was written by an
    older build, and a pre-release suffix ("1.2.3-rc1") should compare on the
    numbers rather than raise.
    """
    numbers: list[int] = []
    for piece in version.strip().lstrip("v").split(".")[:3]:
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def compare_versions(left: str, right: str) -> int:
    """-1, 0 or 1 — the sign of ``left - right`` read as semver."""
    a, b = _parts(left), _parts(right)
    return (a > b) - (a < b)


__version__ = get_version()
