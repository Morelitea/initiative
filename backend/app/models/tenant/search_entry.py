"""The guild-wide search index — one row per searchable chunk of content.

Derived data: every row is written by ``public.refresh_search_entry()`` from the
table it describes, never by application code. See ``app/db/search_index.py``
for the registry that renders those triggers.

The row carries two independent identities. ``(entity_type, entity_id)`` names
what was found, so a hit resolves to a detail route. ``(dac_tool, dac_id)`` names
the resource whose sharing governs it, which is often a *parent* — a task is
governed by its project, a calendar event by its calendar — so the query filters
on the sharing decision without re-walking those joins.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlmodel import Field, SQLModel


class SearchEntry(SQLModel, table=True):
    """One indexed chunk of one entity.

    Composite primary key is ``(entity_type, entity_id, chunk_ix)``. Long text is
    split into several chunks; everything else is a single ``chunk_ix = 0`` row,
    by the same code path.
    """

    __tablename__ = "search_entries"

    # DDL: unbounded TEXT constrained by ck_search_entries_entity_type
    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    chunk_ix: int = Field(
        sa_column=Column(
            SmallInteger, primary_key=True, nullable=False, server_default=text("0")
        )
    )
    #: The initiative gating this row, or NULL for guild-level content (tags, a
    #: guild calendar) where the initiative gate has nothing to decide.
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    #: The ``Tool`` whose sharing governs this row, and the resource id to test
    #: against ``resource_grants``. NULL for rows carrying no sharing gate.
    dac_tool: Optional[str] = Field(sa_column=Column(Text, nullable=True))
    dac_id: Optional[int] = Field(sa_column=Column(Integer, nullable=True))
    title: str = Field(sa_column=Column(Text, nullable=False))
    body: Optional[str] = Field(sa_column=Column(Text, nullable=True))
    #: When this row's *searchable text* last changed — not the source row's
    #: ``updated_at``, which moves on writes the index deliberately ignores.
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    tsv: Optional[str] = Field(default=None, sa_column=Column(TSVECTOR, nullable=False))
