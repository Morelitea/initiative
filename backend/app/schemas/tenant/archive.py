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
