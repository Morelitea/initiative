"""Holds, as the database enforces them: every reportable kind can be held, and
a provisioned schema carries the policy and the guard on each of them."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.search import SearchEntityType
from app.core.tools import plural_of
from app.db.holds import HELD_POLICY, HOLDABLE_TABLES
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild_schema,
)

_GID_HOLDS = 990_471


@pytest.mark.always
def test_everything_a_person_can_report_can_be_held():
    """A new kind is holdable the day it ships: declaring ``HoldMixin`` is what
    puts it here, and this is what makes leaving it off fail."""
    reportable = {plural_of(kind.value) for kind in SearchEntityType}
    assert HOLDABLE_TABLES == reportable | {"uploads"}


async def test_a_provisioned_schema_hides_and_guards_every_holdable_table(engine):
    schema = guild_schema_name(_GID_HOLDS)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_HOLDS)
        async with engine.connect() as conn:
            policies = {
                (row.tablename, row.policyname): row
                for row in await conn.execute(
                    text(
                        "SELECT tablename, policyname, permissive, cmd, qual"
                        " FROM pg_policies WHERE schemaname = :s"
                    ),
                    {"s": schema},
                )
            }
            triggers = {
                (row[0], row[1])
                for row in await conn.execute(
                    text(
                        "SELECT c.relname, t.tgname FROM pg_trigger t"
                        " JOIN pg_class c ON c.oid = t.tgrelid"
                        " JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = :s AND NOT t.tgisinternal"
                    ),
                    {"s": schema},
                )
            }
        for table in sorted(HOLDABLE_TABLES):
            policy = policies.get((table, HELD_POLICY))
            assert policy is not None, f"{table} has no {HELD_POLICY}"
            assert policy.permissive == "RESTRICTIVE"
            assert policy.cmd == "ALL"
            assert (table, f"tr_{table}_held_guard") in triggers

        # The platform's record has no leg for the community.
        record = {
            name: row
            for (table, name), row in policies.items()
            if table == "content_holds"
        }
        assert record
        for row in record.values():
            assert "guild_admin" not in (row.qual or "")
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_HOLDS)
