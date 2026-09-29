from typing import Any, Optional

from pydantic import Base64Bytes, BaseModel


class CollaborationHandover(BaseModel):
    """Edits a tab made while its room's socket was closed, handed over as the
    tab leaves.

    ``update`` is the Yjs update the room has not seen and ``state_vector`` is
    the tab's own, so the room can tell whether ``content`` — the editor's
    rendering of the tab's document — also describes the merged one.
    """

    update: Base64Bytes
    state_vector: Base64Bytes
    content: Optional[dict[str, Any]] = None
