"""Payloads for the owner's intake settings page."""

from __future__ import annotations

from typing import List, Optional

from app.core.intake import IntakeStream
from app.schemas.base import SanitizedBaseModel


class IntakeBindingRead(SanitizedBaseModel):
    """One stream and where it currently lands."""

    stream: IntakeStream
    binding_id: Optional[int] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    #: The bound project has been archived or trashed. Archived content takes
    #: no writes, so the stream receives nothing until it is brought back or
    #: pointed at a live project.
    project_archived: bool = False
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    default_status_id: Optional[int] = None
    default_status_name: Optional[str] = None
    enabled: bool = False
    #: When this stream last opened a case. The one number worth watching on
    #: this page: whether the thing is on.
    last_case_at: Optional[str] = None


class IntakeSettingsRead(SanitizedBaseModel):
    """The pointer, and every stream whether bound or not."""

    operations_guild_id: Optional[int] = None
    operations_guild_name: Optional[str] = None
    bindings: List[IntakeBindingRead]


class OperationsGuildUpdate(SanitizedBaseModel):
    """Point this deployment's operations work at a guild, or at nothing."""

    guild_id: Optional[int] = None


class IntakeBindingUpsert(SanitizedBaseModel):
    """Route one stream into a project of the operations guild."""

    project_id: int
    default_status_id: Optional[int] = None
    enabled: bool = True


class IntakeBlueprintImport(SanitizedBaseModel):
    """Set a stream up from its committed blueprint, in this initiative."""

    initiative_id: int


class IntakeStatusOption(SanitizedBaseModel):
    """One column a case could land in."""

    id: int
    name: str


class IntakeProjectOption(SanitizedBaseModel):
    """One project a stream could be bound to, and where a case would start."""

    id: int
    name: str
    statuses: List[IntakeStatusOption]


class IntakeInitiativeOption(SanitizedBaseModel):
    """One initiative of the operations guild, and the projects in it."""

    id: int
    name: str
    projects: List[IntakeProjectOption]


class IntakeOptionsRead(SanitizedBaseModel):
    """What the settings page offers to bind to.

    The operations guild alone, names and ids only — enough to fill the
    pickers. Empty until a guild has been named.
    """

    initiatives: List[IntakeInitiativeOption]
