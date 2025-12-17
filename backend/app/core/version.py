"""Version utilities for reading application version."""

from pathlib import Path


def get_version() -> str:
    """Read version from VERSION file at project root."""
    version_file = Path(__file__).parent.parent.parent.parent / "VERSION"
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        return "0.0.0"


__version__ = get_version()
