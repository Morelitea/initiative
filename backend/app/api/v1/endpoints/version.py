"""Version endpoint."""

from fastapi import APIRouter

from app.core.version import __version__

router = APIRouter()


@router.get("/version")
def get_version() -> dict[str, str]:
    """Get application version."""
    return {"version": __version__}
