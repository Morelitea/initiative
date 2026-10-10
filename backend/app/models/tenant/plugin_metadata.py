"""What an installed plug-in keeps in Initiative: its own values, by key.

A row is one key's value, on one item or on the install itself. The item is
named by ``(entity_type, entity_id)``, where ``entity_type`` is one of
``ITEM_KINDS``; the install's own values are on ``('plugin', <install id>)``.
There is no foreign key to the item: the purge removes an item's values
explicitly, as it does its property values. The install is a foreign key, so
uninstalling removes everything it kept.

``lookup`` is the value as text when the value is a JSON string, number or
boolean short enough to look up by, and ``NULL`` otherwise.

``shown`` says the install's pinned definition declares the key as a field on
the item's kind. It is set on every write and again whenever the install moves
to another version; the install's own values are never shown.

Read and written by the install that owns the row, on an item it can read,
with the read scope of the item's tool; a shown row is also read by whoever
can read its item (``app.db.initiative_rls`` and ``app.db.guild_ddl``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.db.registry_checks import FROM_REGISTRY
from app.core.tools import METADATA_TARGETS

_TARGET_VALUES = ", ".join(f"'{target}'" for target in METADATA_TARGETS)

#: The longest ``lookup`` kept. A longer scalar is stored with no lookup.
LOOKUP_LENGTH = 255


class PluginMetadata(SQLModel, table=True):
    __tablename__ = "plugin_metadata"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_TARGET_VALUES})",
            name="ck_plugin_metadata_entity_type",
            info={FROM_REGISTRY: True},
        ),
        Index(
            "ix_plugin_metadata_lookup",
            "install_id",
            "key",
            "lookup",
            postgresql_where=text("lookup IS NOT NULL"),
        ),
        Index("ix_plugin_metadata_entity", "entity_type", "entity_id"),
    )

    #: The install that keeps the value. Its rows go with it.
    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    entity_type: str = Field(sa_column=Column(String(32), primary_key=True))
    entity_id: int = Field(sa_column=Column(Integer, primary_key=True))
    key: str = Field(sa_column=Column(String(64), primary_key=True))
    value: Any = Field(sa_column=Column(JSONB, nullable=False))
    lookup: Optional[str] = Field(
        default=None, sa_column=Column(String(LOOKUP_LENGTH), nullable=True)
    )
    #: Declared as a field on the item's kind by the install's pinned version.
    shown: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
