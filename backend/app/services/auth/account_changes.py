"""What an account notice records about its change, and undoing it.

Four notices can be undone from their "This wasn't me" link: an address proved,
the primary moved, an address removed, a passkey added. Each records, when it
is queued, what undoing it would do, whether the change was risky, and the
proof time of the newest address involved. The worker gives a copy the power
to undo only where the change was risky and the copy's address was proved
before that newest one; :func:`apply_undo` carries it out.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_EMAIL, decrypt_field, hash_email
from app.core.login_methods import LoginMethod
from app.models.platform.user_email import UserEmail
from app.models.platform.user_passkey import UserPasskey
from app.services.auth import addresses

#: How far back an undone address removal also takes away the addresses proved
#: after the one it puts back.
SEQUENCE_WINDOW = timedelta(hours=1)


class UndoRefused(Exception):
    """The account has moved on from what the link would undo."""


async def change_record(
    session: AsyncSession,
    *,
    user_id: int,
    risky: bool,
    undo: dict[str, Any],
) -> dict[str, Any]:
    """What an undoable notice carries: whether its change was risky, when it
    happened, the proof time of the newest address on the account, and what
    undoing it does.

    Called while the account still holds every address involved, so a removed
    address counts towards the newest.
    """
    newest = (
        await session.exec(
            select(func.max(UserEmail.verified_at)).where(UserEmail.user_id == user_id)
        )
    ).one()
    return {
        "risky": risky,
        "at": datetime.now(timezone.utc).isoformat(),
        "newest": newest.isoformat() if newest else None,
        "undo": undo,
    }


def removal_undo(row: UserEmail, *, primary_id: int | None) -> dict[str, Any]:
    """What undoing the removal of ``row`` puts back, while ``primary_id`` is
    still the account's primary."""
    return {
        "kind": "removed",
        "email": row.email_encrypted,
        "proved_at": row.verified_at.isoformat() if row.verified_at else None,
        "primary_id": primary_id,
    }


def removed_address(change: dict[str, Any]) -> str | None:
    """The address a removal notice is about, for the copy sent to it."""
    undo = change.get("undo") or {}
    if undo.get("kind") != "removed" or not undo.get("email"):
        return None
    return decrypt_field(undo["email"], SALT_EMAIL)


def may_undo(
    change: dict[str, Any], *, proved_at: datetime | None, removed_copy: bool
) -> bool:
    """Whether the copy sent to an address proved at ``proved_at`` may undo.

    Only a risky change, and only from an address proved before the newest one
    involved. Putting a removed address back is the removed address's own to
    ask for; every other undo belongs to the addresses the account still holds.
    """
    undo = change.get("undo")
    newest = change.get("newest")
    if not change.get("risky") or not undo or proved_at is None or newest is None:
        return False
    if (undo.get("kind") == "removed") != removed_copy:
        return False
    return proved_at < datetime.fromisoformat(newest)


async def subject_of(
    session: AsyncSession, *, user_id: int, change: dict[str, Any]
) -> str | None:
    """What an undo acts on, as the notice named it: an address, or a
    passkey's name."""
    undo = change.get("undo") or {}
    kind = undo.get("kind")
    if kind == "removed":
        return removed_address(change)
    if kind in ("proved", "primary"):
        row = await session.get(UserEmail, undo.get("address_id"))
        if row is None or row.user_id != user_id:
            return None
        return decrypt_field(row.email_encrypted, SALT_EMAIL)
    if kind == "passkey":
        passkey = await session.get(UserPasskey, undo.get("passkey_id"))
        return passkey.name if passkey and passkey.user_id == user_id else None
    return None


async def apply_undo(
    session: AsyncSession,
    *,
    user_id: int,
    change: dict[str, Any],
    clicked_from: str | None,
) -> None:
    """Undo the change a notice reported, staged in ``session``.

    ``clicked_from`` is the hash of the address the link was sent to. Raises
    :class:`UndoRefused` where the account no longer holds what the undo needs.
    """
    undo = change.get("undo") or {}
    kind = undo.get("kind")
    if kind == "primary":
        await _still_primary(
            session, user_id=user_id, address_id=undo.get("made_primary")
        )
        await _make_primary(session, user_id=user_id, address_id=undo.get("address_id"))
    elif kind == "proved":
        await _take_back_address(
            session,
            user_id=user_id,
            address_id=undo.get("address_id"),
            clicked_from=clicked_from,
        )
    elif kind == "removed":
        await _put_back_address(session, user_id=user_id, change=change)
    elif kind == "passkey":
        await _take_back_passkey(
            session, user_id=user_id, passkey_id=undo.get("passkey_id")
        )
    else:
        raise UndoRefused()


async def _still_primary(
    session: AsyncSession, *, user_id: int, address_id: Any
) -> None:
    """Refuse unless ``address_id`` is still the account's primary: a later
    change of primary stands over an earlier notice."""
    row = await session.get(UserEmail, address_id) if address_id is not None else None
    if row is None or row.user_id != user_id or not row.is_primary:
        raise UndoRefused()


async def _make_primary(
    session: AsyncSession, *, user_id: int, address_id: Any
) -> None:
    try:
        await addresses.set_primary_for_user(
            session, user_id=user_id, address_id=address_id
        )
    except addresses.AddressError as exc:
        raise UndoRefused() from exc


async def _held_by_hash(
    session: AsyncSession, *, user_id: int, digest: str | None
) -> UserEmail | None:
    if digest is None:
        return None
    return (
        await session.exec(
            select(UserEmail).where(
                UserEmail.user_id == user_id,
                UserEmail.email_hash == digest,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).first()


async def _take_back_address(
    session: AsyncSession, *, user_id: int, address_id: Any, clicked_from: str | None
) -> None:
    row = await session.get(UserEmail, address_id)
    if row is None or row.user_id != user_id:
        raise UndoRefused()
    if row.is_primary:
        # The primary goes to the address the link was sent to, which the
        # account held before this one.
        keeper = await _held_by_hash(session, user_id=user_id, digest=clicked_from)
        if keeper is None:
            raise UndoRefused()
        await _make_primary(session, user_id=user_id, address_id=keeper.id)
    await session.delete(row)
    await session.flush()


async def _put_back_address(
    session: AsyncSession, *, user_id: int, change: dict[str, Any]
) -> None:
    email = removed_address(change)
    undo = change.get("undo") or {}
    proved_at = undo.get("proved_at")
    if email is None or proved_at is None:
        raise UndoRefused()
    await _still_primary(session, user_id=user_id, address_id=undo.get("primary_id"))
    if await addresses.find_user_by_address(session, email) is not None:
        raise UndoRefused()
    digest = hash_email(addresses.normalize(email))
    # A claim this account made on the address since gives way to the proof
    # being put back.
    await session.exec(
        delete(UserEmail).where(
            UserEmail.user_id == user_id, UserEmail.email_hash == digest
        )
    )
    proved = datetime.fromisoformat(proved_at)
    restored = addresses.record_address(
        session,
        user_id=user_id,
        email=email,
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
        now=proved,
    )
    await session.flush()
    await _make_primary(session, user_id=user_id, address_id=restored.id)
    # The addresses proved after it in the run of changes that removed it go;
    # one added after the removal is the account's own business and stays.
    removed_at = datetime.fromisoformat(change["at"])
    await session.exec(
        delete(UserEmail).where(
            UserEmail.user_id == user_id,
            UserEmail.id != restored.id,
            UserEmail.verified_at > proved,
            UserEmail.verified_at >= removed_at - SEQUENCE_WINDOW,
            UserEmail.verified_at <= removed_at,
        )
    )
    await session.flush()


async def _take_back_passkey(
    session: AsyncSession, *, user_id: int, passkey_id: Any
) -> None:
    from app.services.auth import identity as identity_service
    from app.services.auth import passkeys as passkey_service

    ways = await identity_service.ways_in(session, user_id=user_id)
    if not (ways - {LoginMethod.passkey}) and (
        await passkey_service.count_for_user(session, user_id=user_id) == 1
    ):
        raise UndoRefused()
    if not await passkey_service.remove(
        session, user_id=user_id, passkey_id=passkey_id
    ):
        raise UndoRefused()
