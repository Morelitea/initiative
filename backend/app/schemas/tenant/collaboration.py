from pydantic import Base64Bytes, BaseModel


class CollaborationHandover(BaseModel):
    """Edits a tab made while its room's socket was closed, handed over as the
    tab leaves: the Yjs update the room has not seen."""

    update: Base64Bytes
