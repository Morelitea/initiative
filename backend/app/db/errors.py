"""Helpers for reading Postgres error details off wrapped DBAPI exceptions."""

from sqlalchemy.exc import DBAPIError

INSUFFICIENT_PRIVILEGE_SQLSTATE = "42501"
FOREIGN_KEY_VIOLATION_SQLSTATE = "23503"


def dbapi_sqlstate(exc: DBAPIError) -> str | None:
    """Best-effort SQLSTATE off a wrapped DBAPI error (asyncpg adapter nests
    the real exception one level down as ``orig.__cause__``)."""
    orig = getattr(exc, "orig", None)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        code = getattr(candidate, "sqlstate", None) or getattr(
            candidate, "pgcode", None
        )
        if code:
            return code
    return None
