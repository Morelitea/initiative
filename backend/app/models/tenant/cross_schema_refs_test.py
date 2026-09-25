"""Guard: a guild-schema column that names a person declares no delete rule.

Guild content lives in a per-guild schema and ``users`` lives in ``public``,
and provisioning renders a guild schema from ``guild_template`` copying
intra-schema keys only (``app.db.guild_ddl.render_guild_schema_ddl``). No
``guild_<id>`` has ever held a key out of its own schema, and ``20260921_0347``
and ``20260922_0349`` dropped the ones the template alone still carried.

``foreign_key="users.id"`` stays on the models, because it is what says this
integer names a *person* — that is what gives a filter on the column a member
picker instead of a number box (``app.services.fields.derive``), and what the
search gate reads. A delete rule beside it says something else: that Postgres
will clear the column, or take the row, when the account goes. Fourteen
declarations said so, and none of them ever ran anywhere.

What actually happens to those rows is ``app.services.platform.users``, which
walks every guild schema and deletes or nulls them itself — see
``users_test.py``, where each table's outcome is asserted rather than declared.

Pure metadata checks — no database required.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.db.tenancy import GUILD_SCOPED_TABLES, SHARED_TABLES


def _crossings() -> list[tuple[str, str, str, ForeignKey]]:
    """Every foreign key from a guild-schema table to a shared/public one."""
    found: list[tuple[str, str, str, ForeignKey]] = []
    for name, table in sorted(SQLModel.metadata.tables.items()):
        if name not in GUILD_SCOPED_TABLES:
            continue
        for column in table.columns:
            for fk in column.foreign_keys:
                target = fk.column.table.name
                if target in SHARED_TABLES:
                    found.append((name, column.name, target, fk))
    return found


def test_no_guild_column_declares_a_delete_rule_across_the_boundary():
    declared = [
        f"{table}.{column} -> {target} "
        f"(ondelete={fk.ondelete!r}, onupdate={fk.onupdate!r})"
        for table, column, target, fk in _crossings()
        if fk.ondelete or fk.onupdate
    ]
    assert not declared, (
        "These guild-schema columns declare a rule no guild schema holds: "
        f"{declared}. Keep the foreign_key — it says the column names a "
        "person — and drop the ondelete/onupdate. What happens to the rows "
        "belongs in app.services.platform.users and its tests."
    )


def test_the_boundary_is_actually_crossed():
    """Guards the check above against passing on an empty set."""
    assert len(_crossings()) > 50


def test_nothing_shared_references_a_guild_table():
    """The other direction: ``public`` names no row below the boundary."""
    reaching_down = [
        f"{name}.{column.name} -> {fk.column.table.name}"
        for name, table in sorted(SQLModel.metadata.tables.items())
        if name in SHARED_TABLES
        for column in table.columns
        for fk in column.foreign_keys
        if fk.column.table.name in GUILD_SCOPED_TABLES
    ]
    assert not reaching_down, (
        f"Shared tables holding a key into a guild schema: {reaching_down}."
    )
