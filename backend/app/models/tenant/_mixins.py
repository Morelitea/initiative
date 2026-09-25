"""Mixins shared by guild-schema (tenant) tables only.

This module lives under ``app/models/tenant/`` on purpose: every mixin here is
part of the per-guild **content** lifecycle and is mixed into ``table=True``
models that live in a ``guild_<id>`` schema. **Platform/public tables never use
these** — trash/restore/purge is a guild-content concern, so there is no
table-less "shared by both" bucket at the models root. ``layout_test.py`` fails
CI if a ``SoftDeleteMixin`` subclass ever lands outside ``app/models/tenant/``.
"""

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Optional, TypeVar

from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import column_property
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.core.tools import Tool

_M = TypeVar("_M", bound=SQLModel)


class SoftDeleteMixin(SQLModel):
    """Mixin that adds the trash-can lifecycle columns to a guild-scoped model.

    `_display_field` names the column that labels a row wherever the app shows
    a bare list of mixed entity types (the recents tab bar, the trash can).
    It defaults to `name`; only models that call it something else override it.

    ``deleted_by`` names the person who binned the row, and is the one
    person-naming column here that declares no ``foreign_key`` at all — see
    the note on it below.
    """

    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
    # NOTE: no ``foreign_key=`` here, deliberately. SQLAlchemy would then see
    # two references from this table to users (``created_by`` + this one) and
    # fail to auto-determine join conditions on relationships that join to
    # users. Audit lookups go through the trash service, never through an ORM
    # relationship, so SQLAlchemy doesn't need the metadata.
    deleted_by: Optional[int] = Field(default=None, nullable=True)
    purge_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )

    _display_field: ClassVar[str] = "name"

    @classmethod
    def display_field(cls) -> str:
        return cls._display_field


class ArchiveMixin(SQLModel):
    """Mixin that adds the archive lifecycle column to a guild-scoped model.

    Archiving says *this is finished*; the trash says *this is going away*. They
    are different states with the same shape, so they carry the same shape of
    column: one nullable timestamp, null while live, stamped when it happens.
    ``archived_at`` reads beside ``deleted_at`` and answers "when?" as well as
    "whether?", which a boolean never could.

    Anything an initiative offers can be finished with, so every tool carries
    it, and so do the two things that are not tools but are still worked
    through and put away: a task and an initiative itself.

    Archived content is read-only, down through everything inside it — the rule
    is ``app.db.frozen``, which reads this column and ``deleted_at`` together
    and derives the archivable tables from this mixin.
    """

    archived_at: Optional[datetime] = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )


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

    ``foreign_key`` here is SQLAlchemy metadata, never a constraint: guild
    content lives in a per-guild schema and ``users`` in ``public``, and a
    guild schema holds no key out of it (20260922_0349). What it is for is
    saying that this integer names a *person*, which is what gives a filter on
    ``created_by`` a member picker instead of a number box
    (``app.services.fields.derive``). Reading an author goes through
    ``MemberProfile``, whose relationships spell out their own join because
    the target is a view — so no delete rule is declared for a rule the
    database would not hold.

    That makes ``created_by`` a **weak reference**, and deliberately so: it
    survives the erasure of the account it names, which is what keeps an old
    thread telling one departed author from another. An id with no row behind
    it renders as a former member rather than merging into a shared
    placeholder.

    Every other column in a guild schema that names a person reads the same
    way, author or not. What becomes of those rows when an account closes is
    ``app.services.platform.users.hard_delete_user``, which walks every guild
    schema and deletes or nulls them itself; ``cross_schema_refs_test.py``
    holds the line at no column here declaring a rule instead.

    ``created_by_test.py`` fails CI if a guild-schema table carries neither
    this mixin nor an entry in ``tenancy.CREATED_BY_EXEMPT_TABLES``.
    """

    created_by: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True
    )


class ListingProvenanceMixin(SQLModel):
    """Mixin that records which marketplace listing a tool item came from.

    Installing a listing is importing a copy of it, and the copy keeps two
    facts about where it came from: the listing's ``uid`` and the version it
    was taken at. Both are NULL on anything made here, which is almost
    everything. There is no link back and no update stream — the copy belongs
    to whoever installed it — so these are a record, not a reference, and no
    foreign key reaches the catalog.

    Every tool has a marketplace, so every tool carries the pair.
    ``tools_test.py`` fails CI if a ``Tool`` member's model lacks it. Declared
    without ``sa_column`` so each table builds its own Column.
    """

    listing_uid: Optional[str] = Field(default=None, sa_type=String(14), nullable=True)
    listing_version: Optional[str] = Field(
        default=None, sa_type=String(32), nullable=True
    )


class CommentsToggleMixin(SQLModel):
    """Mixin that adds the per-entity comment switch to a tool's content table.

    Every tool is commentable, so every tool can turn its thread off:
    ``comments_enabled`` is the one column behind that, carrying the same name
    and the same default (on) on every tool. ``tools_test.py`` fails CI if a
    ``Tool`` member's model or read schema lacks it.

    Stated positively — a switch labelled "Comments" is on when comments
    happen, so nobody has to answer yes to mean no.

    The switch belongs to the tool entity, not to its children: a project with
    comments off still has task threads, because a task is its own flow rather
    than a tool surface.

    Declared without ``sa_column`` so each table builds its own Column — one
    Column instance cannot be shared across mapped tables.
    """

    comments_enabled: bool = Field(
        default=True,
        nullable=False,
        sa_column_kwargs={"server_default": "true"},
    )


def _mapped_subclasses(base: type[_M]) -> dict[str, type[_M]]:
    """Every mapped table model under ``base``, however indirectly, by table."""
    found: dict[str, type[_M]] = {}
    stack = list(base.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        table = getattr(cls, "__tablename__", None)
        if table and getattr(cls, "__table__", None) is not None:
            found[str(table)] = cls
    return found


def archive_models() -> list[type[ArchiveMixin]]:
    """Every mapped model carrying :class:`ArchiveMixin`, by table name.

    The single source for "which tables can be archived" — the freeze reads it
    rather than keeping a list of its own, so a tool that becomes archivable is
    archivable everywhere the moment it declares the mixin.
    """
    found = _mapped_subclasses(ArchiveMixin)
    return [found[name] for name in sorted(found)]


def created_by_models() -> list[type[CreatedByMixin]]:
    """Every mapped model carrying :class:`CreatedByMixin`, by table name.

    The single source for "which tables record an author" — the completeness
    test reads it, so a new table joins the moment it declares the mixin.
    """
    found = _mapped_subclasses(CreatedByMixin)
    return [found[name] for name in sorted(found)]


def tool_models() -> dict[str, type[SQLModel]]:
    """Each tool's own content model, keyed by table name.

    A tool's table is its plural — that rule is :class:`~app.core.tools.Tool`'s,
    not this module's — so the registries that map a tool to its model read this
    instead of restating the pairing. A tool added to the enum is picked up the
    moment its model exists, which is what keeps those registries from being a
    place a new tool can be forgotten.
    """
    return _mapped_subclasses(SoftDeleteMixin)


def attach_access_level(model: type[SQLModel], tool: "Tool") -> None:
    """Map ``access_level`` on a shareable model: the rung of the sharing
    ladder the request holds on the row, answered by the schema's own
    ``resource_level`` in the same SELECT as the row.

    Deferred, so a load that only needs the row pays nothing; a loader that
    goes on to serialize the row asks for it with ``undefer``. Read through
    :func:`app.services.permissions.level_of`.
    """
    reader = func.nullif(func.current_setting("app.current_user_id", True), "").cast(
        Integer
    )
    # This statement's standing, as ``app.db.authorization.standing_arg`` spells
    # it; this module sits below that one, so the sub-select is written here.
    standing = select(func.current_standing()).scalar_subquery()
    model.__mapper__.add_property(  # type: ignore[attr-defined]
        "access_level",
        column_property(
            func.resource_level(
                tool.value,
                model.id,  # type: ignore[attr-defined]
                reader,
                model.initiative_id,  # type: ignore[attr-defined]
                standing,
            ),
            deferred=True,
        ),
    )
