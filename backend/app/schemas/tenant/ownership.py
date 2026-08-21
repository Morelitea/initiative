"""Payloads for the guild-admin content-ownership screens."""

from typing import List

from pydantic import ConfigDict, Field

from app.core.tools import Tool
from app.schemas.base import SanitizedBaseModel


class OwnedContentItem(SanitizedBaseModel):
    """One thing someone owns, or that nobody does."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tool: Tool
    id: int
    name: str


class OwnedContentResponse(SanitizedBaseModel):
    """What a user owns in this guild, or what no current member owns.

    ``counts`` is per tool, keyed by the ``Tool`` value, so the dialog can say
    "3 projects, 1 calendar" without walking the list.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[OwnedContentItem] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class OwnershipTransferRequest(SanitizedBaseModel):
    """Who should end up owning it. Must be an active admin of this guild."""

    new_owner_id: int


class OwnershipTransferResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
