"""Payloads for the guild-admin content-ownership screens, and the owning app
a read model names."""

from typing import List, Optional

from pydantic import ConfigDict, Field, model_validator

from app.core.tools import Tool
from app.schemas.base import SanitizedBaseModel


class OwnerAppSummary(SanitizedBaseModel):
    """An installed app that owns a resource, or may be handed one: the
    install's id, its name in this community, and its listing's picture."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    avatar_url: Optional[str] = None


class OwnedContentItem(SanitizedBaseModel):
    """One thing someone owns, or that nobody does."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tool: Tool
    id: int
    name: str


class OwnedContentResponse(SanitizedBaseModel):
    """What a user owns in this guild, or what no current member owns.

    ``counts`` is per tool, keyed by the ``Tool`` value, so the dialog can say
    "3 projects, 1 calendar" without walking the list. ``eligible_apps`` are the
    installed apps that may own every item listed, which the dialog offers
    beside the community's admins.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[OwnedContentItem] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    eligible_apps: List[OwnerAppSummary] = Field(default_factory=list)


class OwnershipTransferRequest(SanitizedBaseModel):
    """Who should end up owning it: an active admin of this guild
    (``new_owner_id``), or an installed app that may own all of it
    (``new_owner_app_id``). Exactly one is set."""

    new_owner_id: Optional[int] = None
    new_owner_app_id: Optional[int] = None

    @model_validator(mode="after")
    def exactly_one_recipient(self) -> "OwnershipTransferRequest":
        if (self.new_owner_id is None) == (self.new_owner_app_id is None):
            raise ValueError("Exactly one of new_owner_id or new_owner_app_id")
        return self


class OwnershipTransferResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
