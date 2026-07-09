"""Schema-invariant audit for the billing boundary tables.

``CHECK (x >= 0)`` passes on NULL, so the CHECK/NULL pairing on each column
is deliberate and must be pinned exactly (write-boundary plan P-2):

* ``guilds.max_storage_bytes`` / ``max_users`` are **nullable by design**
  (NULL = unlimited) with NULL-aware non-negativity CHECKs; ``tier_name``
  nullable (NULL = no paid tier).
* ``billing_event_log``: ``event_id`` PRIMARY KEY; ``guild_id``/``op``/
  ``source`` NOT NULL; ``actor`` nullable; **no FK to guilds** — audit rows
  must survive guild erasure.
* ``billing_jti_blocklist``: ``jti`` PRIMARY KEY; ``expires_at`` NOT NULL
  (the janitor's purge key).

If any of these change, this suite fails and the change needs a reviewed
migration plus an update here (the ``tenancy_test.py`` pattern).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _nullability(session, table: str) -> dict[str, bool]:
    rows = await session.execute(
        text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {name: nullable == "YES" for name, nullable in rows}


async def _constraints(session, table: str, contype: str) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            # contype is "char"; compare as text so asyncpg binds a str param
            "WHERE conrelid = ('public.' || :t)::regclass AND contype::text = :ct"
        ),
        {"t": table, "ct": contype},
    )
    return {name: definition for name, definition in rows}


async def test_guild_cap_columns_nullable_with_nonnegative_checks(session):
    cols = await _nullability(session, "guilds")
    # NULL = unlimited is load-bearing (paid tiers run max_users = NULL);
    # NULL = no paid tier for the display label.
    assert cols["max_storage_bytes"] is True
    assert cols["max_users"] is True
    assert cols["tier_name"] is True

    checks = await _constraints(session, "guilds", "c")
    storage = checks["ck_guilds_max_storage_bytes_nonnegative"]
    users = checks["ck_guilds_max_users_nonnegative"]
    # NULL-aware form: the CHECK constrains values without outlawing NULL.
    assert "max_storage_bytes IS NULL" in storage and ">= 0" in storage
    assert "max_users IS NULL" in users and ">= 0" in users


async def test_billing_event_log_shape(session):
    cols = await _nullability(session, "billing_event_log")
    assert cols["event_id"] is False
    assert cols["guild_id"] is False
    assert cols["op"] is False
    assert cols["source"] is False
    assert cols["applied_at"] is False
    assert cols["actor"] is True  # NULL = automated (webhook-driven) write

    pks = await _constraints(session, "billing_event_log", "p")
    assert list(pks.values()) == ["PRIMARY KEY (event_id)"]

    # No FK: evidence must outlive the guild it describes.
    fks = await _constraints(session, "billing_event_log", "f")
    assert fks == {}, "billing_event_log must not FK guilds (audit rows outlive them)"


async def test_billing_jti_blocklist_shape(session):
    cols = await _nullability(session, "billing_jti_blocklist")
    assert cols["jti"] is False
    assert cols["redeemed_at"] is False
    assert cols["expires_at"] is False

    pks = await _constraints(session, "billing_jti_blocklist", "p")
    assert list(pks.values()) == ["PRIMARY KEY (jti)"]
