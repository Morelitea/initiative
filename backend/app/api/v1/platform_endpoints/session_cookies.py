"""Session/refresh cookie emission shared by the auth and account endpoints.

The session cookie carries the access token ``get_current_user`` reads; the
refresh cookie is scoped to the auth routes so it never rides along on
ordinary API requests — it is only presented to /auth/refresh and /auth/logout.
"""

from fastapi import Response

from app.core.config import API_V1_STR, settings
from app.core.security import REFRESH_COOKIE_NAME, SESSION_COOKIE_NAME

REFRESH_COOKIE_PATH = f"{API_V1_STR}/auth"


def set_session_cookie(response: Response, token: str, *, max_age: int) -> None:
    """Set the session-auth cookie (read by ``get_current_user``). During the
    cutover this holds a legacy JWT on the fallback path and a new-model access
    token otherwise — the verifier accepts either."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=max_age,
        path="/",
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.AUTH_REFRESH_TTL_DAYS * 86400,
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
