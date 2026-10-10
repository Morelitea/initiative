"""Answering an account letter: "This wasn't me".

Every account notice but a lockout carries a link to a page that reads the
token here, says what it will do, and on confirmation signs the account out
everywhere, or undoes the change and signs it out, where the copy was given
that. Either way the people who run the server are told, as a security case
about the account (``app.services.platform.disclosure``); where nothing is set
up to receive it, the page names who to tell instead. The caller holds a
token, not a session, so everything runs on the system engine.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SystemSessionDep
from app.core.audit_events import AuditEventType
from app.core.messages import AuthMessages
from app.core.rate_limit import limiter
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.schemas.platform.auth import (
    AccountChangeDone,
    AccountChangeRead,
    AccountChangeToken,
)
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import account_changes, addresses
from app.services.content_sockets import sockets as content_sockets
from app.services.platform import user_tokens

router = APIRouter()
logger = logging.getLogger(__name__)


def _invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN,
    )


async def _still_answers(system_session: AsyncSession, record: UserToken) -> bool:
    """Whether the address a link went to still stands where it stood.

    A copy to one of the account's addresses holds while that address is
    still proved by the same proof. A copy to an address a removal took away
    holds while nobody has proved that address since.
    """
    change = record.change or {}
    if change.get("removed_copy"):
        removed = account_changes.removed_address(change)
        return (
            removed is not None
            and await addresses.find_user_by_address(system_session, removed) is None
        )
    proved_at = change.get("recipient_proved_at")
    row = (
        await system_session.exec(
            select(UserEmail).where(
                UserEmail.user_id == record.user_id,
                UserEmail.email_hash == account_changes.recipient_hash(change),
                UserEmail.verified_at.is_not(None),
            )
        )
    ).first()
    return (
        row is not None
        and proved_at is not None
        and row.verified_at == datetime.fromisoformat(proved_at)
    )


async def _spend(
    system_session: AsyncSession, token: str
) -> tuple[User, dict[str, Any]]:
    """Spend a link that still answers, staged with the work it does, or
    400."""
    record = await user_tokens.consume_token(
        system_session,
        token=token,
        purpose=UserTokenPurpose.account_change,
        commit=False,
    )
    user = await system_session.get(User, record.user_id) if record else None
    if (
        record is None
        or user is None
        or not await _still_answers(system_session, record)
    ):
        await system_session.rollback()
        raise _invalid()
    return user, record.change or {}


async def _sign_out(
    system_session: AsyncSession, user: User, change: dict[str, Any]
) -> None:
    """Record it, end every session and key, and commit with the spend."""
    undone = (change.get("undo") or {}).get("kind") if change.get("may_undo") else None
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SESSION_REVOKED,
        actor_user_id=user.id,
        target_user_id=user.id,
        target_type="auth_session",
        detail={
            "scope": "everywhere",
            "via": "account_notice",
            "notice": change.get("notice"),
            "undo": undone,
        },
    )
    # ``token_version`` is bumped on ``user``, bound to this session, so it
    # lands on the same commit as the revocations, the record and the spend.
    await user_tokens.revoke_user_sessions(system_session, user=user)
    system_session.add(user)
    await system_session.commit()
    # Open connections stand on the sessions just ended.
    await content_sockets.revoke_user_everywhere(user.id)


async def _tell_the_platform(
    system_session: AsyncSession, user: User, change: dict[str, Any], status: str
) -> AccountChangeDone:
    """File that the account says the change wasn't theirs, and say whether
    anybody was told, or who to tell."""
    from app.core.intake import IntakeStream
    from app.services.platform import disclosure
    from app.services.platform.intake import contact_for

    try:
        case = await disclosure.account_compromised(
            user_id=int(user.id),  # type: ignore[arg-type]
            what_changed=str(change.get("notice") or "an account change"),
        )
    except Exception:  # pragma: no cover - logged; the sign-out stands
        logger.exception("could not file an account compromise")
        case = None
    contact = (
        None
        if case is not None
        else await contact_for(system_session, IntakeStream.security)
    )
    return AccountChangeDone(
        status=status, platform_told=case is not None, contact=contact
    )


@router.post("/account-change/read", response_model=AccountChangeRead)
@limiter.limit("30/15minutes")
async def read_account_change(
    request: Request,
    payload: AccountChangeToken,
    system_session: SystemSessionDep,
) -> AccountChangeRead:
    """What a link answers and may do, for its page to say before anything is
    done. Reading spends nothing."""
    record = await user_tokens.get_valid_token(
        system_session, token=payload.token, purpose=UserTokenPurpose.account_change
    )
    if record is None or not await _still_answers(system_session, record):
        raise _invalid()
    change = record.change or {}
    undo = (change.get("undo") or {}).get("kind") if change.get("may_undo") else None
    return AccountChangeRead(
        notice=change.get("notice", ""),
        sign_out=not change.get("removed_copy"),
        undo=undo,
        subject=(
            await account_changes.subject_of(
                system_session, user_id=record.user_id, change=change
            )
            if undo
            else None
        ),
    )


@router.post("/account-change/sign-out", response_model=AccountChangeDone)
@limiter.limit("10/15minutes")
async def sign_out_everywhere(
    request: Request,
    payload: AccountChangeToken,
    system_session: SystemSessionDep,
) -> AccountChangeDone:
    """Sign the account out of every browser, phone and computer, and turn off
    its API keys, and tell the people who run the server. Its password,
    addresses and other ways in stay as they are. The link is spent with the
    work, so a sign-out that fails leaves it good."""
    user, change = await _spend(system_session, payload.token)
    if change.get("removed_copy"):
        await system_session.rollback()
        raise _invalid()
    await _sign_out(system_session, user, {**change, "may_undo": False})
    return await _tell_the_platform(system_session, user, change, "signed_out")


@router.post("/account-change/undo", response_model=AccountChangeDone)
@limiter.limit("10/15minutes")
async def undo_account_change(
    request: Request,
    payload: AccountChangeToken,
    system_session: SystemSessionDep,
) -> AccountChangeDone:
    """Undo the change the notice reported and sign the account out
    everywhere, where this copy of the notice may, and tell the people who run
    the server. The account is told what the undo changed."""
    user, change = await _spend(system_session, payload.token)
    if not change.get("may_undo"):
        await system_session.rollback()
        raise _invalid()
    subject = await account_changes.subject_of(
        system_session, user_id=user.id, change=change
    )
    try:
        await account_changes.apply_undo(
            system_session,
            user_id=user.id,
            change=change,
            clicked_from=account_changes.recipient_hash(change),
        )
    except account_changes.UndoRefused as exc:
        await system_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.ACCOUNT_CHANGE_MOVED_ON,
        ) from exc
    await _sign_out(system_session, user, change)
    await _announce_undo(system_session, user, change, subject or "")
    return await _tell_the_platform(system_session, user, change, "undone")


async def _announce_undo(
    system_session: AsyncSession, user: User, change: dict[str, Any], subject: str
) -> None:
    """Tell the account what the undo changed, as the change itself would."""
    kind = (change.get("undo") or {}).get("kind")
    if kind == "proved":
        await email_service.announce_address_removed(
            system_session, user, address=subject
        )
    elif kind == "primary":
        await email_service.announce_address_change(
            system_session, user, change="primary", address=subject
        )
    elif kind == "removed":
        await email_service.announce_address_change(
            system_session, user, change="proved", address=subject
        )
    elif kind == "passkey":
        await email_service.announce_passkey_change(
            system_session, user, added=False, name=subject
        )
