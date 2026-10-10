"""an initiative's members go with it

In every guild schema:

- ``initiative_members.initiative_id``: the key to the initiative cascades on
  delete, as the keys of its roles and its other rows do, so purging an
  initiative takes its members in the same statement rather than deleting
  them first.
- The constraints still named for teams take the names of what they are:
  the primary keys of ``initiatives`` and ``initiative_members``, the members'
  key and ``projects.initiative_id``'s key.

Each constraint is found by what it is (its table, and the column a key is
on), not by the name it had, so a schema whose history named it differently
converges too. Renaming changes only the catalog. The downgrade puts back the
team names and a members' key that does not cascade.

Revision ID: 20261010_0491
Revises: 20261010_0490
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0491"
down_revision = "20261010_0490"
branch_labels = None
depends_on = None

#: (table, column of a key or None for the primary key, name now, team name)
_NAMES = (
    ("initiatives", None, "initiatives_pkey", "teams_pkey"),
    ("initiative_members", None, "initiative_members_pkey", "team_members_pkey"),
    (
        "projects",
        "initiative_id",
        "projects_initiative_id_fkey",
        "projects_team_id_fkey",
    ),
)
_MEMBER_KEY = ("initiative_members_initiative_id_fkey", "team_members_team_id_fkey")

_FIND = sa.text(
    """
    SELECT c.conname
      FROM pg_constraint c
     WHERE c.conrelid = CAST(:table AS regclass)
       AND c.contype = CAST(:kind AS "char")
       AND (CAST(:column AS text) IS NULL OR EXISTS (
             SELECT 1 FROM pg_attribute a
              WHERE a.attrelid = c.conrelid
                AND a.attnum = ANY (c.conkey)
                AND a.attname = :column))
    """
)


def _name_of(table: str, column: str | None) -> str:
    kind = "p" if column is None else "f"
    return (
        op.get_bind()
        .execute(_FIND, {"table": table, "kind": kind, "column": column})
        .scalar_one()
    )


def _rename(table: str, column: str | None, name: str) -> None:
    current = _name_of(table, column)
    if current != name:
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{current}" TO "{name}"')


def _member_key(name: str, ondelete: str | None) -> None:
    op.drop_constraint(
        _name_of("initiative_members", "initiative_id"),
        "initiative_members",
        type_="foreignkey",
    )
    op.create_foreign_key(
        name,
        "initiative_members",
        "initiatives",
        ["initiative_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table, column, name, _team_name in _NAMES:
        _rename(table, column, name)
    _member_key(_MEMBER_KEY[0], "CASCADE")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    _member_key(_MEMBER_KEY[1], None)
    for table, column, _name, team_name in _NAMES:
        _rename(table, column, team_name)
