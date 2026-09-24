"""The access tokens the app platform's token endpoint issues.

An access token is ``iat_`` followed by a Fernet token (``app.core.encryption``,
under :data:`~app.core.encryption.SALT_APP_ACCESS_TOKEN`) sealing a compact JSON
payload. The app treats it as opaque, as OAuth expects of a client: what it
needs to know comes back beside the token (``expires_in``, ``scope``).

Two kinds:

* an **app token** names only the client, and reaches the listing of that
  app's installs;
* an **installation token** names the community, the install, the client, the
  scopes it carries and, when narrowed, one initiative. It is what a scoped
  route admits.

Reading one is local: a prefix check, one decrypt and MAC, and a parse. No
database read and no key fetch. A token grants nothing on its own: the install
standing recomputes, from rows, what the install may reach on every request.

The life is ten minutes, enforced from the payload's ``exp`` and, as a ceiling,
from the Fernet timestamp.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import InvalidToken

from app.core.encryption import (
    SALT_APP_ACCESS_TOKEN,
    decrypt_field,
    encrypt_field,
)

__all__ = [
    "ACCESS_TOKEN_LIFETIME_SECONDS",
    "ACCESS_TOKEN_PREFIX",
    "AccessTokenError",
    "AppAccessToken",
    "InstallAccessToken",
    "is_access_token",
    "seal_app_token",
    "seal_install_token",
    "unseal_access_token",
]

#: What every access token starts with. A bearer carrying it is never a person.
ACCESS_TOKEN_PREFIX = "iat_"
#: How long an issued token is good for.
ACCESS_TOKEN_LIFETIME_SECONDS = 600

_KIND_APP = "app"
_KIND_INSTALL = "install"


class AccessTokenError(Exception):
    """The value is not an access token this deployment issued and still
    honours: malformed, altered, sealed under another key, or expired."""


@dataclass(frozen=True)
class AppAccessToken:
    """An app token: the client, and nothing in any community."""

    client_id: str
    exp: int


@dataclass(frozen=True)
class InstallAccessToken:
    """An installation token."""

    guild_id: int
    install_id: int
    client_id: str
    scopes: frozenset[str]
    initiative_id: int | None
    exp: int


def is_access_token(value: str | None) -> bool:
    """Whether ``value`` is shaped as an access token. Says nothing about
    whether it is a valid one."""
    return bool(value) and str(value).startswith(ACCESS_TOKEN_PREFIX)


def _seal(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return ACCESS_TOKEN_PREFIX + encrypt_field(body, SALT_APP_ACCESS_TOKEN)


def _expiry(now: float | None) -> int:
    return int(now if now is not None else time.time()) + ACCESS_TOKEN_LIFETIME_SECONDS


def seal_app_token(*, client_id: str, now: float | None = None) -> tuple[str, int]:
    """An app token for ``client_id``, and the ``exp`` it carries."""
    exp = _expiry(now)
    return _seal({"kind": _KIND_APP, "client": client_id, "exp": exp}), exp


def seal_install_token(
    *,
    guild_id: int,
    install_id: int,
    client_id: str,
    scopes: frozenset[str],
    initiative_id: int | None,
    now: float | None = None,
) -> tuple[str, int]:
    """An installation token, and the ``exp`` it carries."""
    exp = _expiry(now)
    return (
        _seal(
            {
                "kind": _KIND_INSTALL,
                "guild_id": int(guild_id),
                "install_id": int(install_id),
                "client": client_id,
                "scopes": sorted(scopes),
                "initiative": int(initiative_id) if initiative_id is not None else None,
                "exp": exp,
            }
        ),
        exp,
    )


def _int(value: Any) -> int:
    # ``bool`` is an ``int`` subclass, and never a row id.
    if isinstance(value, bool) or not isinstance(value, int):
        raise AccessTokenError("expected an integer")
    return value


def _str(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise AccessTokenError("expected a string")
    return value


def unseal_access_token(
    token: str, *, now: float | None = None
) -> AppAccessToken | InstallAccessToken:
    """Read an access token, or raise :class:`AccessTokenError`.

    Runs no database statement.
    """
    if not is_access_token(token):
        raise AccessTokenError("not an access token")
    sealed = token[len(ACCESS_TOKEN_PREFIX) :]
    try:
        body = decrypt_field(
            sealed,
            SALT_APP_ACCESS_TOKEN,
            ttl_seconds=ACCESS_TOKEN_LIFETIME_SECONDS,
        )
    except (InvalidToken, ValueError, TypeError) as exc:
        raise AccessTokenError("could not unseal") from exc
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise AccessTokenError("payload is not JSON") from exc
    if not isinstance(payload, dict):
        raise AccessTokenError("payload is not an object")

    exp = _int(payload.get("exp"))
    if exp <= int(now if now is not None else time.time()):
        raise AccessTokenError("expired")
    client_id = _str(payload.get("client"))
    kind = payload.get("kind")

    if kind == _KIND_APP:
        return AppAccessToken(client_id=client_id, exp=exp)
    if kind != _KIND_INSTALL:
        raise AccessTokenError("unknown kind")

    scopes = payload.get("scopes")
    if not isinstance(scopes, list) or not all(
        isinstance(scope, str) for scope in scopes
    ):
        raise AccessTokenError("scopes must be a list of strings")
    initiative = payload.get("initiative")
    return InstallAccessToken(
        guild_id=_int(payload.get("guild_id")),
        install_id=_int(payload.get("install_id")),
        client_id=client_id,
        scopes=frozenset(scopes),
        initiative_id=None if initiative is None else _int(initiative),
        exp=exp,
    )
