from datetime import datetime
from typing import ClassVar, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class SoftDeleteMixin(SQLModel):
    """Mixin that adds the trash-can lifecycle columns to a model.

    Subclasses set `_owner_field` to the column name of their owning user
    FK so the restore service can detect "owner has left" situations and
    route the user through the reassignment picker. Leave it None for
    guild-scoped resources without a single owner (Tag, Initiative).

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
    # the Alembic migration (20260426_0077). We deliberately don't declare
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

    @classmethod
    def owner_field(cls) -> Optional[str]:
        return cls._owner_field
