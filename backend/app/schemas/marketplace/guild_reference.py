"""Translating one guild reference into another sector's."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.models.platform.identity_ref import REF_MAX_LENGTH, IdentityPurpose
from app.schemas.base import SanitizedBaseModel


class GuildReferenceRequest(SanitizedBaseModel):
    """A reference the caller holds, and the sector it wants the same guild in.

    ``purpose`` names a sector rather than a party, and cannot name ``app``: an
    app sector belongs to one install, and translating between two of those is
    what would let one app learn another's names.
    """

    guild_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
    purpose: IdentityPurpose


class InstallationReferenceRequest(SanitizedBaseModel):
    """The sector an installed app wants its community named in.

    The community is the one the installation token names. ``guild_ref``, when
    given, is the app's own reference for it and has to name that same
    community.
    """

    purpose: IdentityPurpose
    guild_ref: Optional[str] = Field(
        default=None, min_length=1, max_length=REF_MAX_LENGTH
    )


class GuildReferenceRead(SanitizedBaseModel):
    """The same guild, named in the sector that was asked for."""

    purpose: IdentityPurpose
    guild_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
