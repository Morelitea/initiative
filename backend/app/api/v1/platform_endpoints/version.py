"""Version endpoint."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter

from app.core.version import __version__
from app.schemas.platform.version import ChangelogEntry, ChangelogResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/version")
def get_version() -> dict[str, str]:
    """Get application version."""
    return {"version": __version__}


#: How long an answer from Docker Hub is reused. Releases are days apart, and
#: every visitor's sidebar asks, so one fetch serves everybody for a while.
_LATEST_TTL_SECONDS = 6 * 60 * 60

#: How long "no answer" is reused. Short enough that a deployment which comes
#: back online notices soon, long enough that an offline one stops asking.
_LATEST_RETRY_SECONDS = 15 * 60

_DOCKERHUB_TAGS_URL = "https://hub.docker.com/v2/repositories/morelitea/initiative/tags"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class _LatestVersion:
    version: Optional[str] = None
    expires_at: float = 0.0
    #: Whether the last fetch failed, so an outage is logged once rather than
    #: on every retry.
    unreachable: bool = False


_latest = _LatestVersion()
_latest_lock = asyncio.Lock()


async def _fetch_latest_version() -> Optional[str]:
    """The highest semver tag Docker Hub lists for the image."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(_DOCKERHUB_TAGS_URL, params={"page_size": 100})
        response.raise_for_status()
        data = response.json()
    tags = [
        tag["name"]
        for tag in data.get("results", [])
        if isinstance(tag.get("name"), str) and _SEMVER.match(tag["name"])
    ]
    if not tags:
        return None
    return max(tags, key=lambda tag: tuple(int(part) for part in tag.split(".")))


@router.get("/version/latest")
async def get_latest_dockerhub_version() -> dict[str, Optional[str]]:
    """
    The latest released version on Docker Hub (e.g. "0.3.1"). When Docker Hub
    cannot be reached this is the last version it named, or ``None`` if it has
    named none since the process started.

    The answer is fetched once and reused for every caller until it expires,
    so a request never waits on Docker Hub unless the answer has run out.
    """
    if time.monotonic() < _latest.expires_at:
        return {"version": _latest.version}
    async with _latest_lock:
        # Whoever held the lock may have just fetched it.
        if time.monotonic() < _latest.expires_at:
            return {"version": _latest.version}
        try:
            _latest.version = await _fetch_latest_version()
        except Exception as exc:
            if not _latest.unreachable:
                logger.warning(
                    "Could not read the latest version from Docker Hub; "
                    "the update notice stays hidden until it can: %s",
                    exc,
                )
            _latest.unreachable = True
            _latest.expires_at = time.monotonic() + _LATEST_RETRY_SECONDS
        else:
            _latest.unreachable = False
            _latest.expires_at = time.monotonic() + _LATEST_TTL_SECONDS
        return {"version": _latest.version}


@router.get("/changelog")
def get_changelog(version: Optional[str] = None, limit: int = 1) -> ChangelogResponse:
    """
    Get changelog entries.

    If version is provided, returns changes for that specific version.
    If not provided, returns the most recent N versions (default 1).
    """
    try:
        # Try Docker path first: /app/app/api/v1/endpoints/version.py -> /app/CHANGELOG.md
        changelog_path = (
            Path(__file__).parent.parent.parent.parent.parent / "CHANGELOG.md"
        )

        if not changelog_path.exists():
            # Fall back to development path: backend/app/api/v1/endpoints/version.py -> ../../../../../CHANGELOG.md
            changelog_path = (
                Path(__file__).parent.parent.parent.parent.parent.parent
                / "CHANGELOG.md"
            )

        if not changelog_path.exists():
            return ChangelogResponse(entries=[])

        content = changelog_path.read_text()

        # Parse changelog sections
        # Format: ## [version] - date
        # Captures the version, date, and everything until the next ## or end of file
        pattern = r"## \[([^\]]+)\] - ([^\n]+)\n(.*?)(?=\n## |\Z)"
        matches = re.findall(pattern, content, re.DOTALL)

        entries: list[ChangelogEntry] = []
        max_entries = limit if not version else len(matches)

        for version_num, date, changes in matches:
            # Skip if user requested a specific version and this isn't it
            if version and version_num != version:
                continue

            entries.append(
                ChangelogEntry(version=version_num, date=date, changes=changes.strip())
            )

            # If we've collected enough entries, stop
            if len(entries) >= max_entries:
                break

        return ChangelogResponse(entries=entries)

    except Exception as e:
        print(f"Failed to read changelog: {e}")
        return ChangelogResponse(entries=[])
