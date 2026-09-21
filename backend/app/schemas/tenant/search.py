"""Payloads for guild-wide search."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.core.search import SearchEntityType
from app.core.tools import Tool


class SearchHit(BaseModel):
    """One thing found.

    ``entity_type``/``entity_id`` name what was found. ``tool``/``tool_id`` name
    the thing it lives in — a task's project, a calendar event's calendar — which
    is what a client needs to build a route to it, and is the entity itself for a
    tool's own row.
    """

    model_config = ConfigDict(from_attributes=True)

    entity_type: SearchEntityType
    entity_id: int
    title: str
    snippet: Optional[str] = None
    initiative_id: Optional[int] = None
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None


class SearchResults(BaseModel):
    items: List[SearchHit]
    total: int
    limit: int
    offset: int
    #: True when nothing matched what was typed and these are the closest
    #: titles instead — so a reader is told which of the two they are reading.
    fuzzy: bool = False


class SearchSuggestion(BaseModel):
    """A jump-to target for the command palette: enough to render and route."""

    model_config = ConfigDict(from_attributes=True)

    entity_type: SearchEntityType
    entity_id: int
    title: str
    initiative_id: Optional[int] = None
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None
    #: Whether this reader may change the thing, not only open it. A picker
    #: needs it to know which links are theirs to make: a relation describing
    #: its source is the source's to assert, so a thing somebody can only read
    #: cannot be the source of one.
    can_write: bool = False
    #: What the thing it lives in is called, and the initiative it sits in.
    #: A title alone does not identify anything: six projects run from one
    #: template hold six tasks called "Do a thing", and the only difference
    #: between them is which project they are in. ``tool_title`` is None for a
    #: row that IS a tool — a project does not live in a project.
    tool_title: Optional[str] = None
    initiative_name: Optional[str] = None
