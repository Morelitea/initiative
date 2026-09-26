"""The account's own list of where it is signed in, and the way to end one.

Mounted on ``/auth`` beside the routes that open a session, because this is
the other end of the same thing: sign-in writes a row here, and this is where
somebody reads the rows back and closes one they do not recognise.

**Runs on the system engine** (``SystemSessionDep``), filtered by the
authenticated user. ``auth_sessions`` is reached that way everywhere — the
request path is granted nothing on it — and the filter is what makes this the
account's own list rather than a view of the table. What comes back carries no
refresh-token hash; :class:`~app.services.auth.sessions.LiveSession` selects
the columns a person needs to recognise their own laptop and no others.

The native devices the same screen shows are a different credential on a
different table (``user_tokens``), served by ``/auth/device-tokens``. They are
merged into one list by the page, not by an endpoint: one of the two is on its
way out (see ``lib/nativeSession.ts``), and when it goes the list loses a
source rather than a branch.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import AccountHolder, require_first_party_session, SystemSessionDep
from app.api.v1.platform_endpoints.session_opening import current_session_row
from app.core import auth_context
from app.core.audit_events import AuditEventType
from app.core.messages import AuthMessages
from app.core.user_agents import describe, kind_of
from app.models.platform.auth_session import AuthSession
from app.schemas.platform.auth import SignedInSessionInfo
from app.services import audit as audit_service
from app.services.auth import sessions as session_service
from app.services.platform import user_tokens
from app.services.content_sockets import sockets as content_sockets

router = APIRouter()

#: The account's own sign-ins are listed and ended by the person, in a session of
#: their own, not through a standing credential.
FirstPartyOnly = Annotated[str, Depends(require_first_party_session)]


@router.get("/sessions", response_model=list[SignedInSessionInfo])
async def list_my_sessions(
    request: Request,
    system_session: SystemSessionDep,
    current_user: AccountHolder,
    _first_party: FirstPartyOnly,
) -> list[SignedInSessionInfo]:
    """Every browser session this account can still use, newest activity first.

    Each row is one sign-in rather than one renewal — the service walks each
    live session back to the sign-in it descends from, so a browser left open
    for a month says so.
    """
    current = current_session_row(request)
    rows = await session_service.list_live_for_user(
        system_session, user_id=current_user.id
    )
    return [
        SignedInSessionInfo(
            id=row.id,
            # A native sign-in is handed a name; a browser is not, so its name
            # is read from what it said about itself.
            label=row.device_name or describe(row.user_agent),
            kind=kind_of(row.user_agent),
            ip=row.ip,
            started_at=row.started_at,
            last_used_at=row.last_used_at,
            is_current=current is not None and row.id == current,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    system_session: SystemSessionDep,
    current_user: AccountHolder,
    _first_party: FirstPartyOnly,
    session_id: uuid.UUID,
) -> None:
    """End one of the account's sessions.

    The whole rotation chain, so the session cannot renew its way out of it.
    A session belonging to somebody else answers the same as one that does not
    exist, because the id is the only thing the caller supplied and it should
    not learn which of the two it got wrong.
    """
    row = await system_session.get(AuthSession, session_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.SESSION_NOT_FOUND,
        )
    await session_service.revoke_chain(system_session, session_id=session_id)
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SESSION_REVOKED,
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        target_type="auth_session",
        detail={"scope": "one"},
    )
    await system_session.commit()
    # Connections opened on the ended session close now rather than at the
    # next sweep; the account's others are re-checked and stay.
    await content_sockets.revoke_user_everywhere(current_user.id)


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_other_sessions(
    request: Request,
    system_session: SystemSessionDep,
    current_user: AccountHolder,
    _first_party: FirstPartyOnly,
) -> None:
    """End every session the account holds except the one asking.

    Both credentials, because the list this backs shows both and a button that
    signed out the browsers while leaving the phones would not be telling the
    truth. Which one is spared depends on what the caller is holding: a browser
    session spares its own row and takes every device token, a native client
    spares its own token and takes every session.

    Both tables are the system engine's, so the two halves and the record
    commit together.
    """
    await user_tokens.revoke_other_device_tokens(
        system_session,
        user_id=current_user.id,
        keep_token_id=auth_context.device_token_id(),
    )

    current = current_session_row(request)
    await session_service.revoke_all_for_user(
        system_session,
        user_id=current_user.id,
        except_session_id=str(current) if current is not None else None,
    )
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SESSION_REVOKED,
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        target_type="auth_session",
        detail={"scope": "others"},
    )
    await system_session.commit()
    # The connections this device opened stand on the credential it kept, so
    # they pass the re-check; every other one closes.
    await content_sockets.revoke_user_everywhere(current_user.id)
