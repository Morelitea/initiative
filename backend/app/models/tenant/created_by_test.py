"""Completeness guard for the guild-schema ``created_by`` column.

Every guild-schema table that models something a person made records its author
under ONE name — ``created_by`` — by subclassing ``CreatedByMixin``. That
uniformity is the point: callers that need a row's author (the trash can,
ownership transfer, account erasure) resolve one column name for every table
instead of a per-table lookup, which is what the old spellings (``author_id``,
``uploader_user_id``, ``uploaded_by_id``, ``installed_by_id``,
``created_by_user_id``) cost.

These tests fail if a guild table is in neither bucket — mixin or the explicit
``CREATED_BY_EXEMPT_TABLES`` list — so a new table forces the decision, and if
any table brings one of the old spellings back.

Pure metadata checks — no database required.
"""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.db.tenancy import CREATED_BY_EXEMPT_TABLES, GUILD_SCOPED_TABLES, SHARED_TABLES
from app.models.tenant._mixins import created_by_models

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
    return {str(model.__tablename__) for model in created_by_models()}


def test_every_guild_table_declares_created_by_or_an_exemption():
    unclassified = GUILD_SCOPED_TABLES - _authored_tables() - CREATED_BY_EXEMPT_TABLES
    assert not unclassified, (
        "Guild-schema tables with neither CreatedByMixin nor an entry in "
        f"CREATED_BY_EXEMPT_TABLES: {sorted(unclassified)}. Mix in "
        "CreatedByMixin, or add it to the exempt list with the reason."
    )


def test_exempt_list_names_only_real_guild_tables():
    phantom = CREATED_BY_EXEMPT_TABLES - GUILD_SCOPED_TABLES
    assert not phantom, (
        f"CREATED_BY_EXEMPT_TABLES names non-guild tables: {sorted(phantom)}."
    )


def test_exempt_tables_do_not_also_carry_the_mixin():
    both = CREATED_BY_EXEMPT_TABLES & _authored_tables()
    assert not both, (
        f"Tables both exempt and carrying CreatedByMixin: {sorted(both)}. "
        "Drop the exemption."
    )


def test_created_by_stays_inside_the_guild_schema():
    """The mixin is guild content only — public/platform tables never use it."""
    stray = _authored_tables() & SHARED_TABLES
    assert not stray, (
        f"CreatedByMixin on shared/public tables: {sorted(stray)}. "
        "public holds identity and config, not authored content."
    )


@pytest.mark.parametrize("table", sorted(_authored_tables()))
def test_authored_tables_have_the_column(table: str):
    columns = SQLModel.metadata.tables[table].columns
    assert "created_by" in columns, f"{table} is missing created_by"


def test_updated_by_stays_a_documents_feature():
    """There is no schema-wide "last editor" column, on purpose.

    Who changed a row is captured per transaction into ``event_outbox`` by
    ``public.capture_change``, with the transaction id and the columns that
    changed. A mutable column holds strictly less and is overwritten by the
    next save. ``documents`` keeps one because showing a document's last
    editor is a product feature in its own right.
    """
    carriers = {
        name
        for name, table in SQLModel.metadata.tables.items()
        if "updated_by" in table.columns
    }
    assert carriers == {"documents"}, (
        f"Tables carrying updated_by: {sorted(carriers)}. Only documents should "
        "— everywhere else, who changed a row is event_outbox's answer."
    )


@pytest.mark.parametrize("table", sorted(GUILD_SCOPED_TABLES))
def test_no_table_reintroduces_a_retired_spelling(table: str):
    columns = set(SQLModel.metadata.tables[table].columns.keys())
    clashes = columns & set(RETIRED_SPELLINGS)
    assert not clashes, (
        f"{table} names an attribution column {sorted(clashes)}. "
        "Guild content spells it created_by / updated_by."
    )
