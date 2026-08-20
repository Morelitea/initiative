"""Mixins shared by guild-schema (tenant) tables only.

This module lives under ``app/models/tenant/`` on purpose: every mixin here is
part of the per-guild **content** lifecycle and is mixed into ``table=True``
models that live in a ``guild_<id>`` schema. **Platform/public tables never use
these** — trash/restore/purge is a guild-content concern, so there is no
table-less "shared by both" bucket at the models root. ``layout_test.py`` fails
CI if a ``SoftDeleteMixin`` subclass ever lands outside ``app/models/tenant/``.
"""

from datetime import datetime
from typing import ClassVar, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class SoftDeleteMixin(SQLModel):
    """Mixin that adds the trash-can lifecycle columns to a guild-scoped model.

    Subclasses set `_owner_field` to the column name of their owning user
    FK so the restore service can detect "owner has left" situations and
    route the user through the reassignment picker. Leave it None for
    guild-scoped resources without a single owner (Tag, Initiative).

    `_display_field` names the column that labels a row wherever the app shows
    a bare list of mixed entity types (the recents tab bar, the trash can).
    It defaults to `name`; only models that call it something else override it.

    The ``deleted_by`` FK uses ``foreign_key="users.id"`` for SQLModel
    convenience; the ``ON DELETE SET NULL`` semantic is enforced in the
    Alembic migration that adds the column, matching the existing
    convention in this codebase.
    """

    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
    # NOTE: the FK constraint to users(id) ON DELETE SET NULL is created in
    # the Alembic migration (20260426_0078). We deliberately don't declare
    # foreign_key= here because SQLAlchemy would then see two FKs from this
    # table to users (the entity's owning user FK + this audit FK) and fail
    # to auto-determine join conditions on existing relationships like
    # Project.owner. Audit lookups go through the trash service, never
    # through an ORM relationship, so SQLAlchemy doesn't need the metadata.
    deleted_by: Optional[int] = Field(default=None, nullable=True)
    purge_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )

    _owner_field: ClassVar[Optional[str]] = None
    _display_field: ClassVar[str] = "name"

    @classmethod
    def owner_field(cls) -> Optional[str]:
        return cls._owner_field

    @classmethod
    def display_field(cls) -> str:
        return cls._display_field


class RowAuditMixin(SQLModel):
    """Mixin that adds the two row-attribution columns to a guild-schema table.

    Every content table in a ``guild_<id>`` schema records who created the row
    (``created_by_id``) and who last changed it (``updated_by_id``), under
    those names and no other. The columns exist whether or not the API
    surfaces them, so anything that needs a row's actor — the trash can,
    ownership transfer, account erasure, an access review — resolves one
    column name for every table instead of a per-table lookup. That is what
    the old spellings (``author_id``, ``uploader_user_id``, ``uploaded_by_id``,
    ``installed_by_id``, ``created_by_user_id``) cost, and why they are gone.

    **This is current-state attribution, not an audit trail.** ``updated_by_id``
    holds only the most recent writer; the previous one is gone the moment
    someone else saves. A question of the form "who changed this, and when"
    is answered by the append-only change log, not by these columns — see
    ``history/pam-audit-sink-design.md``. They are a supporting control, and a
    convenience for reads that want to show an actor without a join.

    Individual tables may read the columns as something narrower: a comment's
    ``created_by_id`` is its author, a grant's is who granted it, an installed
    app's is who installed it. That is a domain reading of one generic column,
    which is why the column is not named for any of them.

    Both are nullable: a row can predate the columns or outlive knowing who
    made it. The tables that already required a creator keep ``NOT NULL`` by
    redeclaring ``created_by_id`` — the mixin is the floor, not a ceiling.

    ``foreign_key`` here is ORM metadata — it is what lets relationships like
    ``Task.creator`` resolve their join — not a constraint in the guild
    schemas. Guild content lives in a per-guild schema and ``users`` in
    ``public``, and the guild DDL carries a cross-schema user FK on only a
    handful of tables, so no delete rule is declared for a rule the database
    would not hold. Erasure is enforced in the app instead:
    ``app.services.platform.users.reassign_user_content`` sweeps every table
    carrying this mixin, so a new one is covered the moment it is declared.

    ``row_audit_test.py`` fails CI if a guild-schema table carries neither
    this mixin nor an entry in ``tenancy.ROW_AUDIT_EXEMPT_TABLES``.
    """

    created_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    updated_by_id: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
    )


def row_audit_models() -> list[type[RowAuditMixin]]:
    """Every mapped model carrying :class:`RowAuditMixin`, by table name.

    The single source for "which tables record an actor" — the erasure sweep
    (``reassign_user_content``) and the completeness test both read it, so a
    new table joins both the moment it declares the mixin.
    """
    found: dict[str, type[RowAuditMixin]] = {}
    stack = list(RowAuditMixin.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        table = getattr(cls, "__tablename__", None)
        if table and getattr(cls, "__table__", None) is not None:
            found[str(table)] = cls
    return [found[name] for name in sorted(found)]
