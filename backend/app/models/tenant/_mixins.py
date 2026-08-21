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


class CreatedByMixin(SQLModel):
    """Mixin that adds ``created_by`` to a guild-schema table.

    One column, one name, on every guild-schema table that models something a
    person made. It records the **author**: who made this row, as a historical
    fact. Authorship never transfers — ownership is a live permission and lives
    in ``resource_grants`` (see ``app.services.tenant.ownership``), and the two
    were conflated for a long time under a column named for one and used as the
    other.

    The column exists whether or not the API surfaces it, so anything that
    needs a row's author — the trash can, ownership transfer, account erasure —
    resolves one column name for every table instead of a per-table lookup.
    That is what the old spellings (``author_id``, ``uploader_user_id``,
    ``uploaded_by_id``, ``installed_by_id``, ``created_by_user_id``) cost.

    **The database fills it, not the app.** A BEFORE INSERT trigger
    (``public.fn_set_created_by``, attached per table) reads
    ``app.current_user_id`` — the GUC the request already sets for RLS — so
    every insert is covered, including one that never passes through the ORM.
    Only NULL is filled, so a caller that names an author explicitly keeps it,
    and a write with no user in context (background jobs, seeding, migrations)
    leaves NULL because there is nobody to name. One consequence worth knowing:
    a freshly flushed object holds ``None`` until it is refreshed — the value
    is on the row, not yet in the identity map.

    **There is deliberately no ``updated_by``, anywhere.** Who changed a row,
    and when, is recorded per transaction by ``public.capture_change`` into
    ``event_outbox`` — with the transaction id and the columns that changed,
    which a single mutable column could never hold. ``documents`` carried one
    until it was checked and found to be written on six paths and read on
    none; ``created_by_test.py`` now holds the line at zero.

    Nullable: a row can predate the column or outlive knowing who made it. The
    tables that already required a creator keep ``NOT NULL`` by redeclaring
    ``created_by`` — the mixin is the floor, not a ceiling. The name pairs with
    ``SoftDeleteMixin.deleted_by`` above: both say who, neither carries an
    ``_id`` suffix.

    ``foreign_key`` here is ORM metadata — it is what lets relationships like
    ``Task.creator`` resolve their join — not a constraint in the guild
    schemas. Guild content lives in a per-guild schema and ``users`` in
    ``public``, and the guild DDL carries a cross-schema user FK on only a
    handful of tables, so no delete rule is declared for a rule the database
    would not hold. Erasure is enforced in the app instead:
    ``app.services.platform.users.reassign_user_content`` sweeps every table
    carrying this mixin, so a new one is covered the moment it is declared.

    ``created_by_test.py`` fails CI if a guild-schema table carries neither
    this mixin nor an entry in ``tenancy.CREATED_BY_EXEMPT_TABLES``.
    """

    created_by: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
    )


def created_by_models() -> list[type[CreatedByMixin]]:
    """Every mapped model carrying :class:`CreatedByMixin`, by table name.

    The single source for "which tables record an author" — the erasure sweep
    (``reassign_user_content``) and the completeness test both read it, so a
    new table joins both the moment it declares the mixin.
    """
    found: dict[str, type[CreatedByMixin]] = {}
    stack = list(CreatedByMixin.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        table = getattr(cls, "__tablename__", None)
        if table and getattr(cls, "__table__", None) is not None:
            found[str(table)] = cls
    return [found[name] for name in sorted(found)]
