"""The delivery service: a key directory, a roster, and a queue.

Everything here treats a message as bytes. Nothing in this module branches on
what a payload contains: no key to it exists on the server, which is also why
there is nothing to configure about retention, moderation or search.

Four things it does, and nothing else: publish public keys, hand a sender the
keys it needs, write ciphertext to the recipients' queues, and delete a row once
its recipient has collected it.

Authorisation is the rule the permission layer already shipped. This module
calls ``dm_apparent_permission`` for what the caller may be *told*, and
``dm_deliverable`` for what actually reaches somebody — the difference is the
recipient's ignore list, which the sender's own session cannot read and is never
told about.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import DirectMessageTransportMessages as Messages
from app.models.platform.dm_conversation import (
    DmConversation,
    DmConversationKind,
    DmConversationMember,
    roster_key,
)
from app.models.platform.dm_device import DmDevice
from app.models.platform.dm_one_time_key import DmOneTimeKey
from app.models.platform.dm_queue import DmQueueItem
from app.schemas.platform.dm_transport import (
    MAX_GROUP_MEMBERS,
    MAX_ONE_TIME_KEYS,
    MAX_PAYLOAD_BYTES,
    DmConversationRead,
    DmDeviceRead,
    DmOneTimeKeyUpload,
    DmOutboundMessage,
    DmQueueItemRead,
    DmSessionKey,
)

#: A public key is 32 bytes on both curves.
KEY_BYTES = 32

#: How much undelivered ciphertext one account may be holding. Generous by
#: design: a padded text message is about a kilobyte, so this is on the order of
#: seventeen thousand messages nobody has collected on any device.
QUEUE_CEILING_BYTES = 50 * 1024 * 1024

#: How many messages one collection returns.
QUEUE_PAGE = 200


@dataclass(frozen=True)
class DmSendOutcome:
    """What a send did, in the terms the sender may be told."""

    #: How many messages the server took. All of them, or the send failed.
    accepted: int
    #: Members something was actually written for, so they can be woken. Never
    #: reported to the sender: it is the answer an ignore is meant to withhold.
    reached: tuple[int, ...]
    #: Members whose mailbox was too full to take it. A fact about capacity
    #: rather than about permission, so this one is theirs to see.
    queue_full: tuple[int, ...]
    #: Whether this went to a group, so the bell and the push can name the
    #: thread by who is on it rather than by the one other party.
    group: bool = False


class DmTransportError(Exception):
    """Raised with a message code the endpoint turns into a status."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _decode(value: str, *, expect: int | None = None) -> bytes:
    """Read one base64 value the client published.

    The ratchet writes base64 without the trailing ``=``, which is what Olm has
    always put on the wire. Python's decoder requires it, so it is restored
    here rather than asked of every client.
    """
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DmTransportError(Messages.MALFORMED_KEY) from exc
    if expect is not None and len(raw) != expect:
        raise DmTransportError(Messages.MALFORMED_KEY)
    if not raw:
        raise DmTransportError(Messages.MALFORMED_KEY)
    return raw


def _encode(raw: bytes) -> str:
    """Write one base64 value back, padded.

    Deliberately not the mirror of `_decode`. What the client sends is written
    by two different encoders -- keys by the ratchet library, which omits the
    padding, and ciphertext by this crate's own helper, which keeps it -- and
    only the ciphertext side reads a value back. That reader is strict, so the
    padding stays on; `_decode` is the tolerant half because it is the one that
    has to take both.
    """
    return base64.b64encode(raw).decode("ascii")


async def _permission(session: AsyncSession, target_id: int) -> str:
    """What the caller may do about that account, as the caller sees it."""
    return (
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=target_id)
        )
    ).scalar_one()


async def _deliverable(session: AsyncSession, target_id: int) -> bool:
    """Whether anything the caller sends that account actually arrives.

    The answer is never returned to the caller. Where it is false the write
    still succeeds and simply reaches nobody, so an account that has stopped
    hearing from somebody does not announce it by behaving differently.
    """
    return (
        await session.exec(
            text("SELECT public.dm_deliverable(:t)").bindparams(t=target_id)
        )
    ).scalar_one()


async def _queue_bytes(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            text("SELECT public.dm_queue_bytes(:u)").bindparams(u=user_id)
        )
    ).scalar_one()


async def _own_device(
    session: AsyncSession, *, user_id: int, device_id: uuid.UUID
) -> DmDevice:
    device = await session.get(DmDevice, device_id)
    if device is None or device.user_id != user_id:
        raise DmTransportError(Messages.DEVICE_NOT_FOUND)
    return device


# --------------------------------------------------------------------------
# Devices and keys
# --------------------------------------------------------------------------


async def register_device(
    session: AsyncSession,
    *,
    user_id: int,
    identity_key: str,
    fingerprint_key: str,
    fallback_key: DmOneTimeKeyUpload,
    one_time_keys: list[DmOneTimeKeyUpload],
    label: str | None,
    device_token_id: int | None = None,
) -> DmDevice:
    """Publish a new installed client's public keys.

    A fallback key is required rather than optional: without one, a device whose
    prekeys run out becomes unreachable to anyone starting a new conversation,
    and the failure would land on the sender.

    ``device_token_id`` names the installation this key store belongs to, taken
    from the credential that authenticated the call rather than from the body.
    It is what lets a message wake this device and no other, so a client that
    registers without one (the web, which has no device token) simply never
    holds one -- it is not something a caller may assert about itself.
    """
    device = DmDevice(
        user_id=user_id,
        identity_key=_decode(identity_key, expect=KEY_BYTES),
        fingerprint_key=_decode(fingerprint_key, expect=KEY_BYTES),
        label=label,
        device_token_id=device_token_id,
    )
    session.add(device)
    await session.flush()
    if device_token_id is not None:
        # A re-registering installation brings its key store with it. The row it
        # replaces must not go on naming it, or a push would be aimed at a store
        # whose private half this browser no longer has.
        await _claim_device_token(
            session,
            user_id=user_id,
            device_id=device.id,
            device_token_id=device_token_id,
        )

    session.add(
        DmOneTimeKey(
            device_id=device.id,
            key_id=fallback_key.key_id,
            public_key=_decode(fallback_key.public_key, expect=KEY_BYTES),
            fallback=True,
        )
    )
    _add_one_time_keys(session, device_id=device.id, keys=one_time_keys)
    await session.flush()
    return device


def _add_one_time_keys(
    session: AsyncSession, *, device_id: uuid.UUID, keys: list[DmOneTimeKeyUpload]
) -> None:
    seen: set[str] = set()
    for key in keys:
        if key.key_id in seen:
            raise DmTransportError(Messages.DUPLICATE_KEY_ID)
        seen.add(key.key_id)
        session.add(
            DmOneTimeKey(
                device_id=device_id,
                key_id=key.key_id,
                public_key=_decode(key.public_key, expect=KEY_BYTES),
                fallback=False,
            )
        )


async def add_one_time_keys(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    keys: list[DmOneTimeKeyUpload],
) -> int:
    """Top a device's pool back up. Returns how many it now holds."""
    await _own_device(session, user_id=user_id, device_id=device_id)
    held = await _unclaimed_count(session, device_id)
    if held + len(keys) > MAX_ONE_TIME_KEYS:
        raise DmTransportError(Messages.TOO_MANY_KEYS)
    _add_one_time_keys(session, device_id=device_id, keys=keys)
    await session.flush()
    return held + len(keys)


async def _unclaimed_count(session: AsyncSession, device_id: uuid.UUID) -> int:
    return (
        await session.exec(
            select(func.count())
            .select_from(DmOneTimeKey)
            .where(
                DmOneTimeKey.device_id == device_id,
                DmOneTimeKey.fallback.is_(False),
            )
        )
    ).one()


async def list_devices(session: AsyncSession, *, user_id: int) -> list[DmDeviceRead]:
    devices = list(
        (
            await session.exec(
                select(DmDevice)
                .where(DmDevice.user_id == user_id)
                .order_by(DmDevice.created_at)
            )
        ).all()
    )
    return [
        DmDeviceRead(
            id=device.id,
            identity_key=_encode(device.identity_key),
            fingerprint_key=_encode(device.fingerprint_key),
            label=device.label,
            created_at=device.created_at,
            last_seen_at=device.last_seen_at,
            one_time_key_count=await _unclaimed_count(session, device.id),
        )
        for device in devices
    ]


async def remove_device(
    session: AsyncSession, *, user_id: int, device_id: uuid.UUID
) -> None:
    """Drop a device's keys and everything queued for it.

    This is the one thing that removes an undelivered message, and it is a
    visible act by the person who owns the mailbox.
    """
    device = await _own_device(session, user_id=user_id, device_id=device_id)
    await session.delete(device)
    await session.flush()


async def claim_session_keys(
    session: AsyncSession, *, target_id: int
) -> list[DmSessionKey]:
    """The keys the caller needs to open a session with each of that account's
    devices, spending one prekey per device.

    A claim is a delete: a prekey that cannot be handed out twice needs no state
    to say so. The reusable fallback key is the exception, and is what a device
    whose pool is drained answers with.
    """
    if await _permission(session, target_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)

    devices = list(
        (
            await session.exec(
                select(DmDevice)
                .where(DmDevice.user_id == target_id)
                .order_by(DmDevice.created_at)
            )
        ).all()
    )
    claimed: list[DmSessionKey] = []
    for device in devices:
        # One statement, one key. The request path holds no DELETE on another
        # account's pool, and two callers racing take different rows rather
        # than the same one.
        upload = await _claim_for(session, device.id)
        claimed.append(
            DmSessionKey(
                device_id=device.id,
                identity_key=_encode(device.identity_key),
                fingerprint_key=_encode(device.fingerprint_key),
                one_time_key=upload,
            )
        )
    await session.flush()
    return claimed


async def _claim_for(
    session: AsyncSession, device_id: uuid.UUID
) -> DmOneTimeKeyUpload | None:
    """Spend one prekey from a device, or take its reusable fallback."""
    row = (
        await session.exec(
            text(
                "SELECT key_id, public_key FROM public.dm_claim_one_time_key(:d)"
            ).bindparams(d=device_id)
        )
    ).first()
    if row is None:
        return None
    return DmOneTimeKeyUpload(key_id=row[0], public_key=_encode(bytes(row[1])))


async def directory(session: AsyncSession, *, target_id: int) -> list[DmSessionKey]:
    """That account's devices and their public keys, claiming nothing.

    A recipient needs the sender's identity key to derive the session a pre-key
    message describes, and the queue row carries no sender -- so it reads the
    directory for the one other account its conversation has. Spending a prekey
    to answer an inbound message would drain the pool for no reason.
    """
    if await _permission(session, target_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)
    devices = list(
        (
            await session.exec(
                select(DmDevice)
                .where(DmDevice.user_id == target_id)
                .order_by(DmDevice.created_at)
            )
        ).all()
    )
    return [
        DmSessionKey(
            device_id=device.id,
            identity_key=_encode(device.identity_key),
            fingerprint_key=_encode(device.fingerprint_key),
            one_time_key=None,
        )
        for device in devices
    ]


async def own_session_keys(
    session: AsyncSession, *, user_id: int, except_device: uuid.UUID
) -> list[DmSessionKey]:
    """Keys for this account's *other* devices.

    A message has to reach the sender's own clients as well as the recipient's,
    or their phone never shows what they wrote on their laptop. A device of
    yours is as much a separate ratchet as anybody else's, so it needs the same
    keys, claimed the same way -- ``dm_claim_one_time_key`` already lets an
    owner spend from their own pool, and this is the route to it.
    """
    devices = list(
        (
            await session.exec(
                select(DmDevice)
                .where(DmDevice.user_id == user_id, DmDevice.id != except_device)
                .order_by(DmDevice.created_at)
            )
        ).all()
    )
    return [
        DmSessionKey(
            device_id=device.id,
            identity_key=_encode(device.identity_key),
            fingerprint_key=_encode(device.fingerprint_key),
            one_time_key=await _claim_for(session, device.id),
        )
        for device in devices
    ]


async def fingerprints(session: AsyncSession, *, user_id: int) -> list[str]:
    rows = list(
        (
            await session.exec(
                select(DmDevice.fingerprint_key)
                .where(DmDevice.user_id == user_id)
                .order_by(DmDevice.created_at)
            )
        ).all()
    )
    return [_encode(row) for row in rows]


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------


async def _conversation_with_roster(
    session: AsyncSession, *, kind: DmConversationKind, member_ids: Iterable[int]
) -> DmConversation | None:
    """The one conversation made with exactly these people, if it exists.

    Asked of the key rather than by joining the roster back together: the key is
    what the unique index is on, so this reads the same thing the index enforces
    instead of a second expression of it that could disagree.
    """
    return (
        await session.exec(
            select(DmConversation).where(
                DmConversation.kind == kind,
                DmConversation.roster_key == roster_key(member_ids),
            )
        )
    ).first()


async def _open_conversation(
    session: AsyncSession, *, kind: DmConversationKind, member_ids: Iterable[int]
) -> tuple[DmConversation, bool]:
    """Insert the conversation for this roster, or return the one that beat us.

    Two requests for the same roster can both look, both find nothing and both
    insert; the unique index refuses the second. Losing that race means the
    conversation the caller asked for exists, which is the answer they wanted,
    so it is read back rather than returned as an error. The savepoint is what
    keeps the refused insert from taking the surrounding transaction with it.

    The flag says whether this call is the one that made it, so only the winner
    writes the roster.
    """
    try:
        async with session.begin_nested():
            conversation = DmConversation(kind=kind, roster_key=roster_key(member_ids))
            session.add(conversation)
            await session.flush()
        return conversation, True
    except IntegrityError:
        pass
    winner = await _conversation_with_roster(session, kind=kind, member_ids=member_ids)
    if winner is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    return winner, False


async def create_conversation(
    session: AsyncSession, *, actor_id: int, other_id: int
) -> DmConversation:
    """Open the channel an accepted message request earned.

    Idempotent: asking twice returns the conversation that already exists rather
    than a second one, because a roster has one channel — for a pair, which is
    all this opens, that is the rule the pairwise design already stated.

    A conversation somebody has left is not found here, because a conversation
    down to one member releases its roster name — see :func:`leave_conversation`.
    Asking again after somebody left therefore opens a fresh channel, which is
    what it did before a roster was an identity.

    Both members are accepted the moment it is made. An invitation somebody has
    to answer belongs to a roster they did not already agree to, and a pair got
    here by an accepted message request.
    """
    if actor_id == other_id:
        raise DmTransportError(Messages.CANNOT_MESSAGE_SELF)
    members = (actor_id, other_id)
    existing = await _conversation_with_roster(
        session, kind=DmConversationKind.direct, member_ids=members
    )
    if existing is not None:
        return existing
    if await _permission(session, other_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)

    conversation, opened = await _open_conversation(
        session, kind=DmConversationKind.direct, member_ids=members
    )
    if not opened:
        # Somebody else's request got there first and wrote the roster with it.
        return conversation
    now = datetime.now(timezone.utc)
    for member_id in members:
        session.add(
            DmConversationMember(
                conversation_id=conversation.id,
                user_id=member_id,
                accepted_at=now,
            )
        )
    await session.flush()
    return conversation


async def unreachable_pair(
    session: AsyncSession, *, member_ids: Iterable[int]
) -> tuple[int, int] | None:
    """The first two on this roster who cannot message each other, if any.

    Everybody on a group has to be able to reach everybody else — that is what
    makes it a conversation rather than a room where two people can read each
    other and neither can start. The rule is ``can_ask`` both ways, the same
    table a pair passes, asked across the roster.

    Deliberately ``can_ask`` and not "already open": requiring an accepted
    request between every pair would mean nobody could ever be introduced to
    anybody.
    """
    ids = sorted(set(member_ids))
    if len(ids) < 2:
        return None
    row = (
        await session.exec(
            text("SELECT public.dm_roster_unreachable_pair(:ids)").bindparams(ids=ids)
        )
    ).scalar_one()
    if row is None:
        return None
    return (row[0], row[1])


async def create_group_conversation(
    session: AsyncSession, *, actor_id: int, member_ids: Iterable[int]
) -> tuple[DmConversation, list[int], list[int]]:
    """Propose a roster, and ask everybody on it who is not already.

    Returns the conversation, the members newly invited — an empty list when the
    roster was already assembled and everybody had answered, which is what
    proposing the same roster twice does — and the roster itself, without the
    caller.

    **Proposing a roster again asks the people who are not on it.** People
    change their minds, and they change their settings, so somebody who declined
    in March may accept in June. It is an invitation rather than a
    re-admission: they answer it the way they answered the first one. Somebody
    still deciding is left alone — they already have it, and a second copy is
    pestering.

    The whole roster is re-checked each time, against settings as they are now.
    That is what lets "they have widened their settings" work at all, and it
    equally means a roster that has since become unreachable is refused.
    """
    members = sorted(set(member_ids) | {actor_id})
    if actor_id in set(member_ids):
        raise DmTransportError(Messages.CANNOT_MESSAGE_SELF)
    if len(members) < 3:
        raise DmTransportError(Messages.ROSTER_TOO_SMALL)
    if len(members) > MAX_GROUP_MEMBERS:
        raise DmTransportError(Messages.ROSTER_TOO_LARGE)
    if await unreachable_pair(session, member_ids=members) is not None:
        raise DmTransportError(Messages.ROSTER_NOT_REACHABLE)

    conversation = await _conversation_with_roster(
        session, kind=DmConversationKind.group, member_ids=members
    )
    opened = False
    if conversation is None:
        conversation, opened = await _open_conversation(
            session, kind=DmConversationKind.group, member_ids=members
        )

    present = set(
        (
            await session.exec(
                select(DmConversationMember.user_id).where(
                    DmConversationMember.conversation_id == conversation.id
                )
            )
        ).all()
    )
    now = datetime.now(timezone.utc)
    invited: list[int] = []
    for member_id in members:
        if member_id in present:
            continue
        # The one proposing has answered by proposing.
        session.add(
            DmConversationMember(
                conversation_id=conversation.id,
                user_id=member_id,
                accepted_at=now if member_id == actor_id else None,
            )
        )
        if member_id != actor_id:
            invited.append(member_id)
    await session.flush()
    others = [member_id for member_id in members if member_id != actor_id]
    return conversation, invited, others


async def accept_invitation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> list[int]:
    """Answer yes, and join the roster. Returns who else is already on it."""
    updated = await session.exec(
        update(DmConversationMember)
        .where(
            DmConversationMember.conversation_id == conversation_id,
            DmConversationMember.user_id == user_id,
            DmConversationMember.accepted_at.is_(None),
        )
        .values(accepted_at=datetime.now(timezone.utc))
    )
    if not updated.rowcount:
        raise DmTransportError(Messages.NO_INVITATION)
    await session.flush()
    return await _other_members(
        session, conversation_id=conversation_id, user_id=user_id
    )


async def _handles_on(
    session: AsyncSession, conversation_id: uuid.UUID
) -> dict[int, str]:
    """What to call each account on one conversation.

    Asked of ``dm_roster_handles`` rather than of ``users``: the request path
    reads its own row there and nothing else below moderator, so a query would
    answer for nobody. The entry point answers only for a conversation the
    caller is named on, and only with the two fields a handle is made of.

    Formatted here rather than in SQL, so there is one place that knows what a
    handle looks like.
    """
    from app.core.usernames import format_handle

    rows = (
        await session.exec(
            text(
                "SELECT member_id, username, discriminator "
                "FROM public.dm_roster_handles(:c)"
            ).bindparams(c=conversation_id)
        )
    ).all()
    return {row[0]: format_handle(row[1], row[2]) for row in rows}


async def list_conversations(
    session: AsyncSession, *, user_id: int
) -> list[DmConversationRead]:
    """Every conversation this account is named on, newest first.

    Named on, not only on: an invitation waiting to be answered is in the list,
    because somewhere to answer it is the point. It is marked ``pending`` so a
    client can tell the two apart.
    """
    mine = select(DmConversationMember.conversation_id).where(
        DmConversationMember.user_id == user_id
    )
    rows = list(
        (
            await session.exec(
                select(
                    DmConversation,
                    DmConversationMember.user_id,
                    DmConversationMember.accepted_at,
                )
                .join(
                    DmConversationMember,
                    DmConversationMember.conversation_id == DmConversation.id,
                )
                .where(DmConversation.id.in_(mine))
                .order_by(DmConversation.created_at.desc())
            )
        ).all()
    )

    # One row per member came back; fold them into one entry per conversation,
    # in the order the query already put them.
    conversations: dict[uuid.UUID, DmConversation] = {}
    others: dict[uuid.UUID, list[int]] = {}
    pending: dict[uuid.UUID, bool] = {}
    for conversation, member_id, accepted_at in rows:
        conversations.setdefault(conversation.id, conversation)
        if member_id == user_id:
            pending[conversation.id] = accepted_at is None
        else:
            others.setdefault(conversation.id, []).append(member_id)

    handles: dict[int, str] = {}
    for conversation_id in others:
        handles.update(await _handles_on(session, conversation_id))

    listed = []
    for conversation_id, conversation in conversations.items():
        roster = sorted(others.get(conversation_id, []))
        if not roster:
            # Everybody else has gone. There is nobody to send to, so it is not
            # a conversation any more.
            continue
        listed.append(
            DmConversationRead(
                id=conversation.id,
                other_user_id=roster[0],
                created_at=conversation.created_at,
                kind=str(conversation.kind),
                member_ids=roster,
                member_handles=[handles.get(member_id, "") for member_id in roster],
                pending=pending.get(conversation_id, False),
            )
        )
    return listed


async def _has_accepted(
    session: AsyncSession, *, conversation_id: uuid.UUID, user_id: int
) -> bool:
    """Whether this account has answered its own invitation to this thread."""
    return (
        await session.exec(
            select(DmConversationMember.user_id).where(
                DmConversationMember.conversation_id == conversation_id,
                DmConversationMember.user_id == user_id,
                DmConversationMember.accepted_at.is_not(None),
            )
        )
    ).first() is not None


async def _other_members(
    session: AsyncSession, *, conversation_id: uuid.UUID, user_id: int
) -> list[int]:
    """Everybody on the conversation except the caller, oldest membership first.

    Accepted members only: somebody who has been asked and has not answered is
    on no roster yet, and nothing is written for them.
    """
    return list(
        (
            await session.exec(
                select(DmConversationMember.user_id)
                .where(
                    DmConversationMember.conversation_id == conversation_id,
                    DmConversationMember.user_id != user_id,
                    DmConversationMember.accepted_at.is_not(None),
                )
                .order_by(DmConversationMember.joined_at, DmConversationMember.user_id)
            )
        ).all()
    )


async def _sole_other_member(
    session: AsyncSession, *, conversation_id: uuid.UUID, user_id: int
) -> int:
    """The other party, where there is exactly one.

    The send path still speaks to one recipient. A roster that is not a pair has
    no single answer to give it, and picking one of several would deliver a
    message to a fraction of the people it was addressed to, so it refuses.
    """
    others = await _other_members(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if len(others) != 1:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    return others[0]


async def leave_conversation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> None:
    """Take this account off a conversation.

    **A conversation down to one member releases its roster name.** One person
    left on it has nobody to send to, so the thread is over — and holding its
    name would mean the two of them could never open a channel again, because
    the name is what a new one would be filed under. Releasing it leaves them
    free to start afresh, which is what leaving and asking again did before a
    roster was an identity.

    A roster with two or more still on it keeps its name. The thread is alive
    for them and the name is how they find it.

    Released before the membership row goes, because it is an act by somebody
    who is still on the conversation.
    """
    conversation = await session.get(DmConversation, conversation_id)
    if conversation is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    remaining = await _other_members(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if len(remaining) < 2:
        await session.exec(
            update(DmConversation)
            .where(DmConversation.id == conversation_id)
            .values(roster_key=None)
        )
    await session.exec(
        delete(DmConversationMember).where(
            DmConversationMember.conversation_id == conversation_id,
            DmConversationMember.user_id == user_id,
        )
    )
    await session.flush()


# --------------------------------------------------------------------------
# The queue
# --------------------------------------------------------------------------


async def _device_owners(
    session: AsyncSession, device_ids: set[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Which account each destination device belongs to.

    Only the devices the caller may see — their own, and those of accounts they
    may message. One that does not come back is a device they have no business
    encrypting to, and its copy is dropped rather than refused, so it is not
    tellable apart from a copy an ignore dropped.
    """
    if not device_ids:
        return {}
    rows = (
        await session.exec(
            select(DmDevice.id, DmDevice.user_id).where(DmDevice.id.in_(device_ids))
        )
    ).all()
    return {device_id: owner for device_id, owner in rows}


async def send(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    messages: list[DmOutboundMessage],
) -> DmSendOutcome:
    """Write one already-encrypted copy to every device that should get it.

    The sender's own devices are always written to, so their other clients
    render their own outbox. Everybody else's are written to only where
    ``dm_deliverable`` says so, and the sender is told the same thing either
    way — the count answered is what they handed over, and it does not move
    when a copy is dropped.

    **A send is refused only where it can reach nobody.** One member of a roster
    being out of reach, or holding a full mailbox, does not stop the rest
    hearing it; a pair is the case where the one recipient is everybody, so the
    refusals that were right for a pair are still exactly what a pair gets.

    The two refusals say different things and are kept apart. Being out of reach
    is read from the *apparent* permission, which the sender can ask for
    directly, so refusing on it tells them nothing new. A full mailbox is a fact
    about capacity, and the recipients it happened to are named in the outcome.
    Neither is ever read from ``dm_deliverable``, because that is the one that
    knows about ignores.
    """
    conversation = await session.get(DmConversation, conversation_id)
    if conversation is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    # The sender has to be on it themselves. Somebody who has been asked and has
    # not answered can see the conversation — that is how they decide — and
    # refusing here is what keeps "seeing it" and "being on it" different
    # things. Answered the way a conversation they are not on is answered.
    if not await _has_accepted(
        session, conversation_id=conversation_id, user_id=user_id
    ):
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)

    # Everybody else on it who has answered, which may be nobody — a roster
    # whose invitations are all outstanding, or a pair the other side has left.
    # Not a refusal: the sender's own copies still land in their own outbox, and
    # anything addressed to somebody not on it is dropped the way every other
    # undeliverable copy is.
    roster = set(
        await _other_members(session, conversation_id=conversation_id, user_id=user_id)
    )

    owners = await _device_owners(
        session, {message.recipient_device_id for message in messages}
    )

    # Decode and attribute the whole bundle before anything is written: an
    # oversized copy fails the send, and who is addressed decides which
    # mailboxes are locked.
    decoded: list[tuple[DmOutboundMessage, bytes, int | None]] = []
    for message in messages:
        raw = _decode(message.payload)
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise DmTransportError(Messages.MESSAGE_TOO_LARGE)
        decoded.append((message, raw, owners.get(message.recipient_device_id)))

    addressed = {owner for _m, _raw, owner in decoded if owner in roster}
    reachable = False
    for recipient in addressed:
        if await _permission(session, recipient) == "open":
            reachable = True
            break
    if addressed and not reachable:
        raise DmTransportError(Messages.NOT_REACHABLE)

    deliverable = {
        recipient for recipient in addressed if await _deliverable(session, recipient)
    }

    incoming: dict[int, int] = {}
    for _message, raw, owner in decoded:
        if owner in deliverable:
            incoming[owner] = incoming.get(owner, 0) + len(raw)

    # Two sends to the same near-full mailbox would otherwise both read the old
    # total and both pass. Taken in a fixed order because two sends into
    # overlapping rosters take the same mailboxes, and taking them in different
    # orders is how each ends up waiting on the other.
    for recipient in sorted(incoming):
        await session.exec(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"dm-queue:{recipient}", 0)
                )
            )
        )
    full = {
        recipient
        for recipient in sorted(incoming)
        if await _queue_bytes(session, recipient) + incoming[recipient]
        > QUEUE_CEILING_BYTES
    }
    if incoming and full == set(incoming):
        # Nobody addressed could take it. Refusing is honest; accepting a
        # message we mean to drop later is not.
        raise DmTransportError(Messages.RECIPIENT_QUEUE_FULL)

    rows = []
    reached: set[int] = set()
    for message, raw, owner in decoded:
        if owner == user_id:
            pass  # An account's own copies always land; they are its outbox.
        elif owner in deliverable and owner not in full:
            reached.add(owner)
        else:
            continue
        rows.append(
            {
                "conversation_id": conversation_id,
                "recipient_device_id": message.recipient_device_id,
                "message_type": message.message_type,
                "payload": raw,
            }
        )

    if rows:
        # A Core insert, deliberately: the ORM would ask for the new id back,
        # and nothing here needs it.
        now = datetime.now(timezone.utc)
        await session.exec(
            insert(DmQueueItem).values([{**row, "created_at": now} for row in rows])
        )
    await session.flush()
    return DmSendOutcome(
        accepted=len(messages),
        reached=tuple(sorted(reached)),
        queue_full=tuple(sorted(full)),
        group=conversation.kind == DmConversationKind.group,
    )


async def _claim_device_token(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    device_token_id: int,
) -> None:
    """Leave this installation named by exactly one of the account's key stores.

    Scoped to the account's own rows: an installation belongs to one account,
    and the id being claimed is the one that authenticated the call.
    """
    await session.exec(
        update(DmDevice)
        .where(
            DmDevice.user_id == user_id,
            DmDevice.id != device_id,
            DmDevice.device_token_id == device_token_id,
        )
        .values(device_token_id=None)
    )


async def collect(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    device_token_id: int | None = None,
) -> list[DmQueueItemRead]:
    """Everything waiting for one device, oldest first.

    The order is not a nicety. A ratchet keeps a bounded number of skipped
    message keys, so handing them over in the order they were written is what
    keeps a client able to read them.

    Collecting is also where the key store learns which installation it belongs
    to. A device registers once and never again, so the link cannot only be
    written at registration: one made before there was a link to write, or one
    whose login has been replaced since, would stay unwakeable for the rest of
    its life. Every poll re-states it instead.

    One installation holds one key store, and taking the link moves it rather
    than copying it. Two devices naming the same installation cannot both be
    woken -- a push would go to the one installation either way -- so the one
    that is no longer collecting under it would look linked while silently
    receiving nothing.
    """
    device = await _own_device(session, user_id=user_id, device_id=device_id)
    if device_token_id is not None and device.device_token_id != device_token_id:
        await _claim_device_token(
            session,
            user_id=user_id,
            device_id=device_id,
            device_token_id=device_token_id,
        )
        device.device_token_id = device_token_id
    rows = list(
        (
            await session.exec(
                select(DmQueueItem)
                .where(DmQueueItem.recipient_device_id == device_id)
                .order_by(DmQueueItem.id)
                .limit(QUEUE_PAGE)
            )
        ).all()
    )
    device.last_seen_at = datetime.now(timezone.utc)
    session.add(device)
    await session.flush()
    return [
        DmQueueItemRead(
            id=row.id,
            conversation_id=row.conversation_id,
            message_type=row.message_type,
            payload=_encode(row.payload),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def acknowledge(
    session: AsyncSession,
    *,
    user_id: int,
    device_id: uuid.UUID,
    message_ids: list[int],
) -> int:
    """Delete what this device has taken. Collection is what empties the queue."""
    await _own_device(session, user_id=user_id, device_id=device_id)
    result = await session.exec(
        delete(DmQueueItem).where(
            DmQueueItem.recipient_device_id == device_id,
            DmQueueItem.id.in_(message_ids),
        )
    )
    await session.flush()
    return result.rowcount or 0


async def unread_counts(session: AsyncSession, *, user_id: int) -> dict[uuid.UUID, int]:
    """How much is waiting, per conversation, across all the caller's devices.

    This counts *uncollected* rows, which is a fact about syncing rather than
    about reading. The badge people see is built on the notification rollup
    instead; this is what a client uses to know there is something to fetch.
    """
    device_ids = select(DmDevice.id).where(DmDevice.user_id == user_id)
    rows = (
        await session.exec(
            select(DmQueueItem.conversation_id, func.count())
            .where(DmQueueItem.recipient_device_id.in_(device_ids))
            .group_by(DmQueueItem.conversation_id)
        )
    ).all()
    return {conversation_id: count for conversation_id, count in rows}
