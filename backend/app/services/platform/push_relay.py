"""This server's registration with BeyondersStudio's push relay.

The relay sends pushes to the official app for any server: iPhone pushes
always, and Android pushes for a server with no Firebase service account of
its own. Its send call is FCM's own, so ``push_notifications`` builds the same
message either way and only the address and the credential differ.

A server registers once (``POST /v1/servers``) and is issued an id and a key.
They are kept beside the service account on ``app_setting_secrets`` (the key
Fernet-encrypted), read and written on the system engine, and cached in this
process. Registering happens on the first push that needs the relay, so a
server whose operator never switches push on never contacts it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import update
from sqlmodel import select

from app.core.config import settings as app_config
from app.core.encryption import SALT_PUSH_RELAY_KEY, decrypt_field, encrypt_field
from app.models.platform.app_setting_secret import AppSettingSecret

logger = logging.getLogger(__name__)

#: The relay's public address.
PUSH_RELAY_URL = "https://push-relay.beyonders.studio"

#: How long after a failed registration this process waits before trying
#: again. The relay allows a few registrations a day per address.
REGISTRATION_RETRY_SECONDS = 300.0

#: How long the relay's Android settings are kept once fetched, and how long a
#: failed fetch is remembered before the next one is tried.
ANDROID_CONFIG_TTL_SECONDS = 3600.0
ANDROID_CONFIG_RETRY_SECONDS = 300.0

#: The longest name the relay takes for a server.
_NAME_MAX = 100

#: The settings singleton's id, which its credentials row shares.
_ROW_ID = 1

_TABLE = AppSettingSecret.__table__
_SERVER_ID = _TABLE.c.push_relay_server_id
_KEY = _TABLE.c.push_relay_key_encrypted


@dataclass(frozen=True)
class AndroidConfig:
    """The Firebase settings the Android app starts with on a relay server."""

    project_id: str
    application_id: str
    api_key: str
    sender_id: str


_credentials: tuple[str, str] | None = None
_lock = asyncio.Lock()
_last_failed_registration: float | None = None

_android: tuple[float, AndroidConfig | None] | None = None
_android_lock = asyncio.Lock()


def send_url(project_id: str | None) -> str:
    """The relay's send call. The project in the path is not read by it."""
    return f"{PUSH_RELAY_URL}/v1/projects/{project_id or 'relay'}/messages:send"


def authorization(server_id: str, key: str) -> str:
    return f"Bearer {server_id}.{key}"


def server_name() -> str:
    """What this server tells the relay it is called: its address's host."""
    host = urlsplit(app_config.APP_URL.strip()).hostname
    return (host or "Initiative server")[:_NAME_MAX]


async def _load_stored() -> tuple[str, str] | None:
    """The stored credential, or None. One that no longer decrypts under
    ``SECRET_KEY`` is cleared, so the next registration can replace it."""
    from app.db import session as db_session  # noqa: PLC0415

    async with db_session.SystemSessionLocal() as system_session:
        row = (
            await system_session.exec(
                select(_SERVER_ID, _KEY).where(_TABLE.c.id == _ROW_ID)
            )
        ).one_or_none()
    if row is None or not row[0] or not row[1]:
        return None
    server_id, encrypted = row
    try:
        return server_id, decrypt_field(encrypted, SALT_PUSH_RELAY_KEY)
    except InvalidToken:
        logger.error(
            "push relay: the stored key does not decrypt under SECRET_KEY; "
            "this server will register with the relay again."
        )
        await _clear_stored(server_id)
        return None


async def _store(server_id: str, key: str) -> tuple[str, str] | None:
    """Keep a new registration unless another process already kept one, and
    answer whichever is stored."""
    from app.db import session as db_session  # noqa: PLC0415
    from app.services.platform.app_settings import (  # noqa: PLC0415
        _ensure_secrets_row,
    )

    async with db_session.SystemSessionLocal() as system_session:
        await _ensure_secrets_row(system_session)
        await system_session.exec(
            update(_TABLE)
            .where(_TABLE.c.id == _ROW_ID, _SERVER_ID.is_(None))
            .values(
                {
                    _SERVER_ID: server_id,
                    _KEY: encrypt_field(key, SALT_PUSH_RELAY_KEY),
                }
            )
        )
        await system_session.commit()
    return await _load_stored()


async def _clear_stored(server_id: str) -> None:
    """Clear the stored credential, if it is still this one."""
    from app.db import session as db_session  # noqa: PLC0415

    async with db_session.SystemSessionLocal() as system_session:
        await system_session.exec(
            update(_TABLE)
            .where(_TABLE.c.id == _ROW_ID, _SERVER_ID == server_id)
            .values({_SERVER_ID: None, _KEY: None})
        )
        await system_session.commit()


async def _register(client: httpx.AsyncClient) -> tuple[str, str] | None:
    try:
        response = await client.post(
            f"{PUSH_RELAY_URL}/v1/servers", json={"name": server_name()}
        )
    except httpx.HTTPError as exc:
        logger.warning("push relay: could not register: %s", exc)
        return None
    if response.status_code != 201:
        logger.error(
            "push relay: registration refused (status %s): %s",
            response.status_code,
            response.text[:200],
        )
        return None
    try:
        body = response.json()
        server_id, key = body["server_id"], body["server_key"]
    except (ValueError, KeyError, TypeError):
        logger.error("push relay: registration answered without a credential")
        return None
    if not (
        isinstance(server_id, str)
        and isinstance(key, str)
        and 0 < len(server_id) <= 64
        and key
    ):
        logger.error("push relay: registration answered without a credential")
        return None
    logger.info("push relay: registered as %s", server_id)
    return server_id, key


async def credentials(client: httpx.AsyncClient) -> tuple[str, str] | None:
    """This server's relay id and key, registering first if it has none.

    None when there is no credential and registering failed; a later call
    tries again, at most once every :data:`REGISTRATION_RETRY_SECONDS`.
    """
    global _credentials, _last_failed_registration
    if _credentials is not None:
        return _credentials
    async with _lock:
        if _credentials is not None:
            return _credentials
        stored = await _load_stored()
        if stored is None:
            if (
                _last_failed_registration is not None
                and time.monotonic() - _last_failed_registration
                < REGISTRATION_RETRY_SECONDS
            ):
                return None
            registered = await _register(client)
            if registered is None:
                _last_failed_registration = time.monotonic()
                return None
            stored = await _store(*registered)
            if stored is None:  # pragma: no cover - the UPDATE landed or lost
                _last_failed_registration = time.monotonic()
                return None
        _last_failed_registration = None
        _credentials = stored
        return _credentials


async def forget(server_id: str) -> None:
    """Drop a credential the relay no longer accepts, here and where it is
    stored, so the next push registers again."""
    global _credentials, _last_failed_registration, _android
    async with _lock:
        if _credentials is not None and _credentials[0] == server_id:
            _credentials = None
        _last_failed_registration = None
        await _clear_stored(server_id)
    if _android is not None and _android[1] is None:
        _android = None
    logger.warning("push relay: %s is no longer accepted; registering again", server_id)


async def android_config(client: httpx.AsyncClient) -> AndroidConfig | None:
    """The relay's Android Firebase settings, or None if it could not say."""
    global _android
    now = time.monotonic()
    if _android is not None and now < _android[0]:
        return _android[1]
    async with _android_lock:
        if _android is not None and time.monotonic() < _android[0]:
            return _android[1]
        config = await _fetch_android_config(client)
        ttl = (
            ANDROID_CONFIG_TTL_SECONDS
            if config is not None
            else ANDROID_CONFIG_RETRY_SECONDS
        )
        _android = (time.monotonic() + ttl, config)
        return config


async def _fetch_android_config(client: httpx.AsyncClient) -> AndroidConfig | None:
    held = await credentials(client)
    if held is None:
        return None
    server_id, key = held
    try:
        response = await client.get(
            f"{PUSH_RELAY_URL}/v1/android-config",
            headers={"Authorization": authorization(server_id, key)},
        )
    except httpx.HTTPError as exc:
        logger.warning("push relay: could not read the Android settings: %s", exc)
        return None
    if response.status_code == 401:
        await forget(server_id)
        return None
    if response.status_code != 200:
        logger.error(
            "push relay: Android settings unavailable (status %s): %s",
            response.status_code,
            response.text[:200],
        )
        return None
    try:
        body = response.json()
        return AndroidConfig(
            project_id=str(body["project_id"]),
            application_id=str(body["application_id"]),
            api_key=str(body["api_key"]),
            sender_id=str(body["sender_id"]),
        )
    except (ValueError, KeyError, TypeError):
        logger.error("push relay: the Android settings were not readable")
        return None


def reset_for_tests() -> None:
    """Drop everything this process holds, so the next call starts over."""
    global _credentials, _last_failed_registration, _android, _lock, _android_lock
    _credentials = None
    _last_failed_registration = None
    _android = None
    _lock = asyncio.Lock()
    _android_lock = asyncio.Lock()
