"""Payloads for the operations community's intake settings.

Which project each stream lands in, and what it could land in. Served on the
community's own routes, to its superadmin, and only in the community the
deployment routes its operations work to.
"""

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


class IntakeBindingsRead(SanitizedBaseModel):
    """Every stream, whether bound or not."""

    bindings: List[IntakeBindingRead]


class IntakeBindingUpsert(SanitizedBaseModel):
    """Route one stream into a project of this community."""

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
    """One initiative of this community, and the projects in it."""

    id: int
    name: str
    projects: List[IntakeProjectOption]


class IntakeOptionsRead(SanitizedBaseModel):
    """What the settings page offers to bind to: names and ids, enough to fill
    the pickers."""

    initiatives: List[IntakeInitiativeOption]
