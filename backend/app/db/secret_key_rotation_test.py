"""Tests for one-shot SECRET_KEY rotation.

The DB-backed tests follow the guild_conversion_test pattern: seed committed rows
via the (superuser) ``engine`` fixture, run the rotation — which reads
``db_session.provisioning_engine`` (pointed at the test engine by the autouse
``_schema_test_harness`` fixture) — then clean up in ``finally``.

Rotation scans ALL rows globally, so assertions target the specific seeded rows.
Rows encrypted under some *other* key are classified ``failed`` and left untouched
(no UPDATE), so they can't be corrupted by these tests.
"""

import pytest
from sqlalchemy import text

from app.core import config
from app.core.encryption import (
    SALT_AI_API_KEY,
    SALT_EMAIL,
    decrypt_field,
    encrypt_field,
    hash_email,
)
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild,
)
from app.db.secret_key_rotation import (
    _rotate_value,
    maybe_rotate_at_startup,
    rotate_secret_key,
)

# Distinct test-only keys (≥32 chars). Deliberately different from the ambient
# test SECRET_KEY so unrelated rows fall into the (untouched) "failed" bucket.
OLD = "o" * 48
NEW = "n" * 48


def _use_keys(monkeypatch, *, old, new) -> None:
    """Point the live settings at NEW (current) + OLD (previous). validate_assignment
    is off, so these assignments don't re-run the strong-key validator."""
    monkeypatch.setattr(config.settings, "SECRET_KEY", new)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", old)


# ── pure classification (no DB) ──────────────────────────────────────────────


def test_rotate_value_skips_when_already_under_new_key():
    already_new = encrypt_field("x", SALT_EMAIL, secret_key=NEW)
    status, value = _rotate_value(already_new, SALT_EMAIL, OLD, NEW)
    assert status == "skipped"
    assert value == already_new


def test_rotate_value_reencrypts_from_old_key():
    old_ct = encrypt_field("x", SALT_EMAIL, secret_key=OLD)
    status, new_ct = _rotate_value(old_ct, SALT_EMAIL, OLD, NEW)
    assert status == "rotated"
    assert decrypt_field(new_ct, SALT_EMAIL, secret_key=NEW) == "x"


def test_rotate_value_reports_failed_when_neither_key_works():
    foreign = encrypt_field("x", SALT_EMAIL, secret_key="z" * 48)
    status, value = _rotate_value(foreign, SALT_EMAIL, OLD, NEW)
    assert status == "failed"
    assert value is None


# ── guards (no DB) ───────────────────────────────────────────────────────────


async def test_rotate_raises_without_previous_key(monkeypatch):
    monkeypatch.setattr(config.settings, "SECRET_KEY", NEW)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", None)
    with pytest.raises(RuntimeError, match="PREVIOUS_SECRET_KEY is not set"):
        await rotate_secret_key()


async def test_rotate_raises_when_keys_equal(monkeypatch):
    monkeypatch.setattr(config.settings, "SECRET_KEY", NEW)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", NEW)
    with pytest.raises(RuntimeError, match="equals SECRET_KEY"):
        await rotate_secret_key()


async def test_maybe_rotate_at_startup_is_noop_when_unset(monkeypatch):
    monkeypatch.setattr(config.settings, "SECRET_KEY", NEW)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", None)
    # Must NOT raise and must not touch the DB.
    await maybe_rotate_at_startup()


# ── end-to-end against real tables ───────────────────────────────────────────

pytestmark = pytest.mark.database


async def _insert_user(conn, email: str, *, key: str) -> int:
    return await conn.scalar(
        text(
            "INSERT INTO public.users "
            "(email_hash, email_encrypted, ai_api_key_encrypted, hashed_password, "
            " created_at, updated_at) "
            "VALUES (:h, :e, :a, 'x', now(), now()) RETURNING id"
        ),
        {
            "h": hash_email(email, secret_key=key),
            "e": encrypt_field(email, SALT_EMAIL, secret_key=key),
            "a": encrypt_field("user-ai-key", SALT_AI_API_KEY, secret_key=key),
        },
    )


async def test_rotate_user_email_hash_and_fernet_columns(engine, monkeypatch):
    """A user seeded under OLD has its email pair AND ai key re-keyed to NEW; the
    recomputed email_hash matches a NEW-key lookup. Second run is idempotent."""
    email = "rot-user@example.com"
    old_hash = hash_email(email, secret_key=OLD)
    user_id = None
    try:
        async with engine.begin() as conn:
            user_id = await _insert_user(conn, email, key=OLD)

        _use_keys(monkeypatch, old=OLD, new=NEW)
        summary = await rotate_secret_key()
        assert summary.rotated >= 2  # email pair (counts once) + ai key

        async with engine.connect() as conn:
            h, e, a = (
                await conn.execute(
                    text(
                        "SELECT email_hash, email_encrypted, ai_api_key_encrypted "
                        "FROM public.users WHERE id = :i"
                    ),
                    {"i": user_id},
                )
            ).one()

        # email_hash recomputed under NEW → a NEW-key lookup now finds this user.
        assert h == hash_email(email, secret_key=NEW)
        assert h != old_hash
        assert decrypt_field(e, SALT_EMAIL, secret_key=NEW) == email
        assert decrypt_field(a, SALT_AI_API_KEY, secret_key=NEW) == "user-ai-key"

        # Idempotent: a second run re-keys nothing (this row is already under NEW).
        again = await rotate_secret_key()
        async with engine.connect() as conn:
            h2 = await conn.scalar(
                text("SELECT email_hash FROM public.users WHERE id = :i"),
                {"i": user_id},
            )
        assert h2 == h  # unchanged
        # Nothing of *ours* rotated again (other rows under foreign keys are ignored).
        assert again.rotated == 0
    finally:
        if user_id is not None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM public.users WHERE id = :i"), {"i": user_id}
                )


async def test_dry_run_reports_but_does_not_write(engine, monkeypatch):
    email = "rot-dry@example.com"
    old_hash = hash_email(email, secret_key=OLD)
    old_email_ct = encrypt_field(email, SALT_EMAIL, secret_key=OLD)
    user_id = None
    try:
        async with engine.begin() as conn:
            user_id = await conn.scalar(
                text(
                    "INSERT INTO public.users "
                    "(email_hash, email_encrypted, hashed_password, created_at, updated_at) "
                    "VALUES (:h, :e, 'x', now(), now()) RETURNING id"
                ),
                {"h": old_hash, "e": old_email_ct},
            )

        _use_keys(monkeypatch, old=OLD, new=NEW)
        summary = await rotate_secret_key(dry_run=True)
        assert summary.rotated >= 1  # would rotate

        async with engine.connect() as conn:
            h, e = (
                await conn.execute(
                    text(
                        "SELECT email_hash, email_encrypted FROM public.users WHERE id = :i"
                    ),
                    {"i": user_id},
                )
            ).one()
        # Untouched: still the OLD hash/ciphertext.
        assert h == old_hash
        assert e == old_email_ct
    finally:
        if user_id is not None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM public.users WHERE id = :i"), {"i": user_id}
                )


async def test_rotate_visits_per_guild_schema_settings(engine, monkeypatch):
    """guild_settings is guild-scoped, so its live rows live in guild_<id> schemas —
    the sweep must re-key those, not just the public copy."""
    gid = None
    try:
        async with engine.begin() as conn:
            gid = await conn.scalar(
                text(
                    "INSERT INTO public.guilds (name) VALUES ('Rot Guild') RETURNING id"
                )
            )
        await provision_guild(gid)  # creates the guild_<id> schema (own transaction)
        schema = guild_schema_name(gid)
        async with engine.begin() as conn:
            # FK checks off so we can seed without a schema-local guild row.
            await conn.execute(
                text("SELECT set_config('session_replication_role', 'replica', true)")
            )
            await conn.execute(
                text(
                    f'INSERT INTO "{schema}".guild_settings '
                    "(guild_id, created_at, updated_at, ai_api_key_encrypted) "
                    "VALUES (:g, now(), now(), :a)"
                ),
                {
                    "g": gid,
                    "a": encrypt_field("guild-ai", SALT_AI_API_KEY, secret_key=OLD),
                },
            )

        _use_keys(monkeypatch, old=OLD, new=NEW)
        await rotate_secret_key()

        async with engine.connect() as conn:
            ct = await conn.scalar(
                text(
                    f'SELECT ai_api_key_encrypted FROM "{schema}".guild_settings '
                    "WHERE guild_id = :g"
                ),
                {"g": gid},
            )
        assert decrypt_field(ct, SALT_AI_API_KEY, secret_key=NEW) == "guild-ai"
    finally:
        if gid is not None:
            async with engine.begin() as conn:
                await drop_guild_schema(conn, gid)
                await conn.execute(
                    text("DELETE FROM public.guilds WHERE id = :g"), {"g": gid}
                )
