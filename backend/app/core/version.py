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


__version__ = get_version()
