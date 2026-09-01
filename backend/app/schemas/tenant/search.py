"""Payloads for guild-wide search."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.core.tools import Tool


class SearchHit(BaseModel):
    """One thing found.

    ``entity_type``/``entity_id`` name what was found. ``tool``/``tool_id`` name
    the thing it lives in — a task's project, a calendar event's calendar — which
    is what a client needs to build a route to it, and is the entity itself for a
    tool's own row.
    """

    model_config = ConfigDict(from_attributes=True)

    entity_type: str
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


class SearchSuggestion(BaseModel):
    """A jump-to target for the command palette: enough to render and route."""

    model_config = ConfigDict(from_attributes=True)

    entity_type: str
    entity_id: int
    title: str
    initiative_id: Optional[int] = None
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None
