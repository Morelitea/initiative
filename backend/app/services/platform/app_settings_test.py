"""Settings rows: where they come from, and what asking for one costs."""

import logging

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.login_methods import DEFAULT_LOGIN_METHODS
from app.models.platform.app_setting import AppSetting
from app.services.platform.app_settings import (
    GLOBAL_SETTINGS_ID,
    _build_default_app_settings,
    ensure_settings_row,
    get_app_settings,
    get_or_create_guild_settings,
    seed_app_settings,
)
from app.testing import create_guild, route_session_to_guild


async def _stored_ids(session: AsyncSession) -> list[int]:
    return list((await session.exec(select(AppSetting.id))).all())


async def test_seeding_creates_the_singleton(session: AsyncSession):
    """Boot is where the row comes from, and saying so twice changes nothing."""
    assert await _stored_ids(session) == []

    first = await seed_app_settings(session)
    assert first.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]

    second = await seed_app_settings(session)
    assert second.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]


async def test_reading_settings_before_the_seed_stores_nothing(session: AsyncSession):
    """Configuration read on a database that has no row yet answers from the env."""
    row = await get_app_settings(session)
    assert row.id == GLOBAL_SETTINGS_ID
    assert row.community_directory_enabled is False
    assert await _stored_ids(session) == []


async def test_reading_settings_leaves_the_transaction_open(session: AsyncSession):
    """A read is a read: the caller's transaction is still theirs afterwards.

    Stated as the transaction id, which is what anything held for the length of
    a transaction — a row lock, an advisory lock — is keyed on.
    """
    before = (await session.exec(text("SELECT txid_current()"))).one()

    await get_app_settings(session)
    assert (await session.exec(text("SELECT txid_current()"))).one() == before

    await seed_app_settings(session)  # the row now exists; read it again
    started = (await session.exec(text("SELECT txid_current()"))).one()
    await get_app_settings(session)
    assert (await session.exec(text("SELECT txid_current()"))).one() == started


async def test_settings_row_for_a_writer_joins_the_transaction(session: AsyncSession):
    """``ensure_settings_row`` puts the row in place without ending the caller."""
    before = (await session.exec(text("SELECT txid_current()"))).one()

    row = await ensure_settings_row(session)
    assert row.id == GLOBAL_SETTINGS_ID
    assert (await session.exec(text("SELECT txid_current()"))).one() == before

    # Still one row, and the same one, when a second caller asks.
    assert (await ensure_settings_row(session)).id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]


async def test_guild_settings_gap_fill_joins_the_transaction(session: AsyncSession):
    """A guild missing its settings row gets one inside the caller's transaction.

    A guild is normally given the row when it is made, so this is the gap-fill
    path. Stated as the transaction id, the same way the platform singleton's
    is: whoever asked still has the transaction they asked from.
    """
    guild = await create_guild(session)  # the factory seeds no settings row
    await route_session_to_guild(session, guild.id)

    started = (await session.exec(text("SELECT txid_current()"))).one()
    row = await get_or_create_guild_settings(session, guild.id)
    assert row.guild_id == guild.id
    assert row.id is not None
    assert (await session.exec(text("SELECT txid_current()"))).one() == started

    # Asking again answers with the row already there, same transaction still.
    assert (await get_or_create_guild_settings(session, guild.id)).id == row.id
    assert (await session.exec(text("SELECT txid_current()"))).one() == started


# --- The sign-in posture the env seeds ------------------------------------

DEFAULT_METHODS = [m.value for m in DEFAULT_LOGIN_METHODS]


def _seed_env(monkeypatch, methods, *, mail: bool = True) -> None:
    monkeypatch.setattr(app_config, "AUTH_LOGIN_METHODS", methods)
    monkeypatch.setattr(app_config, "SMTP_HOST", "smtp.example.com" if mail else None)
    monkeypatch.setattr(
        app_config, "SMTP_FROM_ADDRESS", "app@example.com" if mail else None
    )


def test_env_decides_the_ways_in_of_a_fresh_row(monkeypatch):
    """AUTH_LOGIN_METHODS is stored the way the settings page stores it."""
    _seed_env(monkeypatch, ["sso", "passkey", "totp", "email_otp"])
    assert _build_default_app_settings().login_methods == [
        "email_otp",
        "passkey",
        "sso",
        "totp",
    ]


def test_env_unset_keeps_the_default(monkeypatch):
    _seed_env(monkeypatch, None)
    assert _build_default_app_settings().login_methods == DEFAULT_METHODS


def test_env_value_this_version_does_not_know_is_dropped_and_said(monkeypatch, caplog):
    _seed_env(monkeypatch, ["sso", "magic_link"])
    with caplog.at_level(logging.WARNING):
        assert _build_default_app_settings().login_methods == ["sso"]
    assert "magic_link" in caplog.text


def test_env_with_no_way_to_begin_keeps_the_default(monkeypatch, caplog):
    """The column's CHECK would refuse the row; falling back keeps the
    deployment one somebody can still configure."""
    _seed_env(monkeypatch, ["totp"])
    with caplog.at_level(logging.WARNING):
        assert _build_default_app_settings().login_methods == DEFAULT_METHODS
    assert "begin a session" in caplog.text


def test_env_emailed_code_needs_a_mail_server(monkeypatch, caplog):
    """The rule the settings page enforces on the way up, applied to the seed."""
    _seed_env(monkeypatch, ["sso", "email_otp"], mail=False)
    with caplog.at_level(logging.WARNING):
        assert _build_default_app_settings().login_methods == ["sso"]
    assert "mail server" in caplog.text


async def test_env_seeds_the_row_once(session: AsyncSession, monkeypatch):
    """The env decides a row it creates, and never one that already exists."""
    _seed_env(monkeypatch, ["sso", "passkey"])
    assert (await seed_app_settings(session)).login_methods == ["passkey", "sso"]

    _seed_env(monkeypatch, ["password"])
    assert (await seed_app_settings(session)).login_methods == ["passkey", "sso"]
    assert (await get_app_settings(session)).login_methods == ["passkey", "sso"]
