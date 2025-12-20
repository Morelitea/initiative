"""Version endpoint."""

import re
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException

from app.core.version import __version__

router = APIRouter()


@router.get("/version")
def get_version() -> dict[str, str]:
    """Get application version."""
    return {"version": __version__}


@router.get("/version/latest")
async def get_latest_dockerhub_version() -> dict[str, Optional[str]]:
    """
    Fetch the latest semantic version from DockerHub.

    Returns the latest version tag (e.g., "0.3.1") from the morelitea/initiative repository.
    """

    def parse_semver(version: str) -> tuple[int, int, int]:
        """Parse semantic version string into tuple for comparison."""
        parts = version.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://hub.docker.com/v2/repositories/morelitea/initiative/tags",
                params={"page_size": 100},
            )
            response.raise_for_status()
            data = response.json()

            # Filter for semantic version tags (e.g., "0.3.1", "1.0.0")
            # Exclude "latest" and other non-semver tags
            semver_regex = re.compile(r"^\d+\.\d+\.\d+$")
            version_tags = [
                tag["name"]
                for tag in data.get("results", [])
                if semver_regex.match(tag["name"])
            ]

            if not version_tags:
                return {"version": None}

            # Sort by semantic version (highest first)
            version_tags.sort(key=parse_semver, reverse=True)

            # Return the highest version
            return {"version": version_tags[0]}

    except httpx.HTTPError as e:
        # Log error but don't fail - version check is not critical
        print(f"Failed to fetch DockerHub version: {e}")
        return {"version": None}
    except Exception as e:
        print(f"Unexpected error fetching DockerHub version: {e}")
        return {"version": None}
