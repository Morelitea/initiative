"""Wire shapes for archiving.

``ArchivableType`` is derived from ``ARCHIVE_TARGETS`` the same way the trash
can's ``EntityType`` is derived from ``TRASH_TARGETS``, so a new tool becomes
archivable by joining the ``Tool`` enum rather than by being listed again here.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from app.core.tools import ARCHIVE_TARGETS
from app.schemas.base import SanitizedBaseModel

ArchivableType = Enum(
    "ArchivableType", {name: name for name in ARCHIVE_TARGETS}, type=str
)
ArchivableType.__doc__ = "Things that can be archived."


class ArchiveResponse(SanitizedBaseModel):
    """What archiving or unarchiving answers with.

    The stamp, not the entity: one endpoint serves ten kinds, and a caller that
    wants the whole row reads it back from the route that already serves it.
    """

    entity_type: ArchivableType
    entity_id: int
    archived_at: Optional[datetime] = None


class ArchiveState(SanitizedBaseModel):
    """What a read schema says about the archive, for every tool that has one.

    Mixed into each tool's summary rather than written out on each, so a tool
    cannot end up carrying the stamp without also carrying the way back out —
    which is the state all but three of them were in.
    """

    #: When this was put away, or ``null`` while it is live.
    archived_at: Optional[datetime] = None
    #: Whether the caller may take it back out.
    #:
    #: Server-computed, and deliberately not derivable from the field beside it:
    #: an archived row reports ``read`` for ``my_permission_level`` — the cap
    #: that turns every edit affordance off at once — so the way out has to be
    #: answered separately or it is capped away with everything else. False as
    #: well for a row archived along with the thing above it, which comes back
    #: with that thing rather than on its own.
    can_unarchive: bool = False
