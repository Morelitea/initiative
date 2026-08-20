"""Completeness guard for the guild-schema authorship columns.

Every guild-schema table that models something a person wrote records who wrote
it and who last changed it under ONE pair of names — ``created_by_id`` and
``updated_by_id`` — by subclassing ``AuthorshipMixin``. That uniformity is the
point: callers that need a row's author (the trash can, content transfer,
account erasure) resolve one column name for every table instead of a per-table
lookup, which is what the old spellings (``author_id``, ``uploader_user_id``,
``uploaded_by_id``, ``installed_by_id``, ``created_by_user_id``) cost.

These tests fail if a guild table is in neither bucket — mixin or the explicit
``AUTHORSHIP_EXEMPT_TABLES`` list — so a new table forces the decision, and if
any table brings one of the old spellings back.

Pure metadata checks — no database required.
"""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.db.tenancy import AUTHORSHIP_EXEMPT_TABLES, GUILD_SCOPED_TABLES, SHARED_TABLES
from app.models.tenant._mixins import authorship_models

pytestmark = pytest.mark.unit

#: Spellings this mixin replaced. A table may not reintroduce one.
RETIRED_SPELLINGS = (
    "author_id",
    "uploader_user_id",
    "uploaded_by_id",
    "installed_by_id",
    "created_by_user_id",
)


def _authored_tables() -> set[str]:
    return {str(model.__tablename__) for model in authorship_models()}


def test_every_guild_table_declares_authorship_or_an_exemption():
    unclassified = GUILD_SCOPED_TABLES - _authored_tables() - AUTHORSHIP_EXEMPT_TABLES
    assert not unclassified, (
        "Guild-schema tables with neither AuthorshipMixin nor an entry in "
        f"AUTHORSHIP_EXEMPT_TABLES: {sorted(unclassified)}. Mix in "
        "AuthorshipMixin, or add it to the exempt list with the reason."
    )


def test_exempt_list_names_only_real_guild_tables():
    phantom = AUTHORSHIP_EXEMPT_TABLES - GUILD_SCOPED_TABLES
    assert not phantom, (
        f"AUTHORSHIP_EXEMPT_TABLES names non-guild tables: {sorted(phantom)}."
    )


def test_exempt_tables_do_not_also_carry_the_mixin():
    both = AUTHORSHIP_EXEMPT_TABLES & _authored_tables()
    assert not both, (
        f"Tables both exempt and carrying AuthorshipMixin: {sorted(both)}. "
        "Drop the exemption."
    )


def test_authorship_stays_inside_the_guild_schema():
    """The mixin is guild content only — public/platform tables never use it."""
    stray = _authored_tables() & SHARED_TABLES
    assert not stray, (
        f"AuthorshipMixin on shared/public tables: {sorted(stray)}. "
        "public holds identity and config, not authored content."
    )


@pytest.mark.parametrize("table", sorted(_authored_tables()))
def test_authored_tables_have_both_columns(table: str):
    columns = SQLModel.metadata.tables[table].columns
    assert "created_by_id" in columns, f"{table} is missing created_by_id"
    assert "updated_by_id" in columns, f"{table} is missing updated_by_id"


@pytest.mark.parametrize("table", sorted(GUILD_SCOPED_TABLES))
def test_no_table_reintroduces_a_retired_spelling(table: str):
    columns = set(SQLModel.metadata.tables[table].columns.keys())
    clashes = columns & set(RETIRED_SPELLINGS)
    assert not clashes, (
        f"{table} names an authorship column {sorted(clashes)}. "
        "Guild content spells it created_by_id / updated_by_id."
    )
