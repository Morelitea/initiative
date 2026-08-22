"""Finish the rename in the public schema

``20260820_0188`` gave every guild-schema table one name for its author,
``created_by``. Two shared tables kept the old spelling: ``guilds`` and
``guild_invites`` both carried ``created_by_user_id``. They record the same
fact — who made this row — so they take the same name, and the guard that
forbids the retired spellings now covers every table rather than only the
guild-scoped ones.

This is a plain ``public``-schema migration: neither table is guild-scoped
(they are read before a request is routed), so there is no per-schema loop.

Renamed, not recreated, so the values survive. The two foreign keys named after
the old column are brought along with it.

The columns stay nullable and stay in the model rather than joining
``CreatedByMixin``: that mixin carries guild-schema behaviour with it — a
stamping trigger and the erasure sweep — and ``public`` has neither. What is
shared here is the name, not the mechanism.

Revision ID: 20260820_0189
Revises: 20260820_0188
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op

revision = "20260820_0189"
down_revision = "20260820_0188"
branch_labels = None
depends_on = None

#: table -> old column name. Both become ``created_by``.
_RENAMES: tuple[str, ...] = ("guilds", "guild_invites")
_OLD = "created_by_user_id"
_NEW = "created_by"


def upgrade() -> None:
    for table in _RENAMES:
        op.alter_column(table, _OLD, new_column_name=_NEW, schema="public")
        op.execute(
            f"ALTER TABLE public.{table} RENAME CONSTRAINT "
            f"{table}_{_OLD}_fkey TO {table}_{_NEW}_fkey"
        )


def downgrade() -> None:
    for table in _RENAMES:
        op.execute(
            f"ALTER TABLE public.{table} RENAME CONSTRAINT "
            f"{table}_{_NEW}_fkey TO {table}_{_OLD}_fkey"
        )
        op.alter_column(table, _NEW, new_column_name=_OLD, schema="public")
