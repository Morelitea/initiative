"""Payloads for the owner's intake settings page.

The platform names which community receives operations work and who somebody
is told to contact. Where each stream lands inside that community is the
community's own setting (``app.schemas.tenant.intake``).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import EmailStr, Field

from app.core.intake import IntakeStream
from app.schemas.base import SanitizedBaseModel


class IntakeSettingsRead(SanitizedBaseModel):
    """The pointer, which streams currently receive, and who to contact."""

    operations_guild_id: Optional[int] = None
    operations_guild_name: Optional[str] = None
    #: The streams that currently have an enabled binding in the operations
    #: community. Which project each lands in is that community's to show.
    receiving: List[IntakeStream]
    #: The deployment's catch-all contact address.
    general_contact_email: Optional[str] = None
    #: Each stream's own contact address, for the streams that have one. A
    #: stream absent here falls back to the general address.
    contact_emails: Dict[IntakeStream, str] = Field(default_factory=dict)


class IntakeContactUpdate(SanitizedBaseModel):
    """Set a contact address, or clear it with ``null``."""

    email: Optional[EmailStr] = None


class OperationsGuildUpdate(SanitizedBaseModel):
    """Point this deployment's operations work at a guild, or at nothing."""

    guild_id: Optional[int] = None
