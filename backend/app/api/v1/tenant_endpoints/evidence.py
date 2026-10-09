"""Opening a file attached to a report or an operations case.

One route, for the people working the report or the case: the row is read on
the reader's own routed session, so the report's or the case's own policy
decides whether they may have it, and a file they may not have is the same
404 as one that does not exist. The person who attached a file reads it back
through their tickets (``/me/tickets/{task_id}/evidence/{id}``), not here.

Served without a header — a page shows a picture by address alone — so the
community rides in the path and access is established here, as the file
download routes do.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.api.deps import (
    CommunityIdPath,
    GuildAccessError,
    SessionDep,
    UploadUserDep,
    establish_guild_access,
)
from app.core.audit_events import AuditEventType
from app.core.messages import EvidenceMessages
from app.db.schema_provisioning import guild_schema_name
from app.services import audit as audit_service
from app.services.platform import evidence as evidence_service

router = APIRouter()


@router.get("/{evidence_id}", include_in_schema=False)
async def read_evidence(
    guild_id: CommunityIdPath,
    evidence_id: int,
    current_user: UploadUserDep,
    # Routed below, once access is established for the path's community.
    session: SessionDep,
):
    """One attached file, opened, for whoever may read its report or case."""
    missing = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=EvidenceMessages.NOT_FOUND
    )
    schema_exists = (
        await session.exec(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :ns"),
            params={"ns": guild_schema_name(int(guild_id))},
        )
    ).first()
    if schema_exists is None:
        raise missing
    try:
        await establish_guild_access(session, current_user, int(guild_id))
    except GuildAccessError:
        raise missing from None
    obj = await evidence_service.sealed(session, evidence_id)
    if obj is None:
        raise missing
    audit_service.emit(
        event_type=AuditEventType.EVIDENCE_ACCESSED,
        actor_user_id=int(current_user.id),
        guild_id=int(guild_id),
        target_type="evidence",
        target_id=evidence_id,
        detail={"as": "staff"},
    )
    return evidence_service.serve(int(guild_id), obj)
