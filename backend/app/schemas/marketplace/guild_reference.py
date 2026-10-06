"""Translating one guild reference into another sector's."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.models.platform.identity_ref import REF_MAX_LENGTH, IdentityPurpose
from app.schemas.base import SanitizedBaseModel


class CommunityReferenceRequest(SanitizedBaseModel):
    """A reference the caller holds, and the sector it wants the same guild in.

    ``purpose`` names a sector rather than a party, and cannot name ``plugin``: a
    plug-in sector belongs to one install, and translating between two of those is
    what would let one plug-in learn another's names.
    """

    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
    purpose: IdentityPurpose


class InstallationReferenceRequest(SanitizedBaseModel):
    """The sector an installed plug-in wants its community named in.

    The community is the one the installation token names. ``community_ref``, when
    given, is the plug-in's own reference for it and has to name that same
    community.
    """

    purpose: IdentityPurpose
    community_ref: Optional[str] = Field(
        default=None, min_length=1, max_length=REF_MAX_LENGTH
    )


class CommunityReferenceRead(SanitizedBaseModel):
    """The same guild, named in the sector that was asked for."""

    purpose: IdentityPurpose
    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
