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
from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import DirectMessageTransportMessages as Messages
from app.models.platform.dm_conversation import (
    DmConversation,
    DmConversationMember,
)
from app.models.platform.dm_device import DmDevice
from app.models.platform.dm_one_time_key import DmOneTimeKey
from app.models.platform.dm_queue import DmQueueItem
from app.schemas.platform.dm_transport import (
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
) -> DmDevice:
    """Publish a new installed client's public keys.

    A fallback key is required rather than optional: without one, a device whose
    prekeys run out becomes unreachable to anyone starting a new conversation,
    and the failure would land on the sender.
    """
    device = DmDevice(
        user_id=user_id,
        identity_key=_decode(identity_key, expect=KEY_BYTES),
        fingerprint_key=_decode(fingerprint_key, expect=KEY_BYTES),
        label=label,
    )
    session.add(device)
    await session.flush()

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


async def _existing_conversation(
    session: AsyncSession, *, actor_id: int, other_id: int
) -> DmConversation | None:
    mine = select(DmConversationMember.conversation_id).where(
        DmConversationMember.user_id == actor_id
    )
    row = (
        await session.exec(
            select(DmConversation)
            .join(
                DmConversationMember,
                DmConversationMember.conversation_id == DmConversation.id,
            )
            .where(
                DmConversationMember.user_id == other_id,
                DmConversationMember.conversation_id.in_(mine),
            )
            .limit(1)
        )
    ).first()
    return row


async def create_conversation(
    session: AsyncSession, *, actor_id: int, other_id: int
) -> DmConversation:
    """Open the channel an accepted message request earned.

    Idempotent: asking twice returns the conversation that already exists rather
    than a second one, because a pair has one channel.
    """
    if actor_id == other_id:
        raise DmTransportError(Messages.CANNOT_MESSAGE_SELF)
    existing = await _existing_conversation(
        session, actor_id=actor_id, other_id=other_id
    )
    if existing is not None:
        return existing
    if await _permission(session, other_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)

    conversation = DmConversation()
    session.add(conversation)
    await session.flush()
    # Slot 0 is whoever opened it. The pair of slots is unique per conversation,
    # so a third member is refused by the index rather than by a count somebody
    # else could be reading at the same moment.
    session.add(
        DmConversationMember(conversation_id=conversation.id, user_id=actor_id, slot=0)
    )
    session.add(
        DmConversationMember(conversation_id=conversation.id, user_id=other_id, slot=1)
    )
    await session.flush()
    return conversation


async def list_conversations(
    session: AsyncSession, *, user_id: int
) -> list[DmConversationRead]:
    mine = select(DmConversationMember.conversation_id).where(
        DmConversationMember.user_id == user_id
    )
    rows = list(
        (
            await session.exec(
                select(DmConversation, DmConversationMember.user_id)
                .join(
                    DmConversationMember,
                    DmConversationMember.conversation_id == DmConversation.id,
                )
                .where(
                    DmConversation.id.in_(mine),
                    DmConversationMember.user_id != user_id,
                )
                .order_by(DmConversation.created_at.desc())
            )
        ).all()
    )
    return [
        DmConversationRead(
            id=conversation.id,
            other_user_id=other_id,
            created_at=conversation.created_at,
        )
        for conversation, other_id in rows
    ]


async def _other_member(
    session: AsyncSession, *, conversation_id: uuid.UUID, user_id: int
) -> int:
    other = (
        await session.exec(
            select(DmConversationMember.user_id).where(
                DmConversationMember.conversation_id == conversation_id,
                DmConversationMember.user_id != user_id,
            )
        )
    ).first()
    if other is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    return other


async def leave_conversation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> None:
    conversation = await session.get(DmConversation, conversation_id)
    if conversation is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
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


async def send(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: uuid.UUID,
    messages: list[DmOutboundMessage],
) -> tuple[int, int | None]:
    """Write one already-encrypted message to every device that should get it.

    Returns the number of rows written and, when the other party was written to,
    their account id — the caller uses it to signal them, and it is ``None``
    where nothing reached them.

    The sender's own devices are always written to, so their other clients
    render their own outbox. The other party's devices are written to only if
    ``dm_deliverable`` says so, and the sender is told the same thing either way.
    """
    conversation = await session.get(DmConversation, conversation_id)
    if conversation is None:
        raise DmTransportError(Messages.CONVERSATION_NOT_FOUND)
    other_id = await _other_member(
        session, conversation_id=conversation_id, user_id=user_id
    )
    if await _permission(session, other_id) != "open":
        raise DmTransportError(Messages.NOT_REACHABLE)

    own_device_ids = set(
        (
            await session.exec(select(DmDevice.id).where(DmDevice.user_id == user_id))
        ).all()
    )
    delivers = await _deliverable(session, other_id)

    payloads: list[tuple[DmOutboundMessage, bytes, bool]] = []
    incoming_bytes = 0
    for message in messages:
        raw = _decode(message.payload)
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise DmTransportError(Messages.MESSAGE_TOO_LARGE)
        mine = message.recipient_device_id in own_device_ids
        if not mine and not delivers:
            continue
        if not mine:
            incoming_bytes += len(raw)
        payloads.append((message, raw, mine))

    if incoming_bytes:
        # Two sends to the same near-full mailbox would otherwise both read the
        # old total and both pass. Transaction-scoped, and keyed on the
        # recipient, so only sends to the same person ever wait.
        await session.exec(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"dm-queue:{other_id}", 0)
                )
            )
        )
    if incoming_bytes and (
        await _queue_bytes(session, other_id) + incoming_bytes > QUEUE_CEILING_BYTES
    ):
        # Refusing is honest. Accepting a message we mean to drop later is not.
        raise DmTransportError(Messages.RECIPIENT_QUEUE_FULL)

    if payloads:
        # A Core insert, deliberately: the ORM would ask for the new id back,
        # and nothing here needs it.
        now = datetime.now(timezone.utc)
        await session.exec(
            insert(DmQueueItem).values(
                [
                    {
                        "conversation_id": conversation_id,
                        "recipient_device_id": message.recipient_device_id,
                        "message_type": message.message_type,
                        "payload": raw,
                        "created_at": now,
                    }
                    for message, raw, _mine in payloads
                ]
            )
        )
    await session.flush()
    return len(payloads), other_id if delivers else None


async def collect(
    session: AsyncSession, *, user_id: int, device_id: uuid.UUID
) -> list[DmQueueItemRead]:
    """Everything waiting for one device, oldest first.

    The order is not a nicety. A ratchet keeps a bounded number of skipped
    message keys, so handing them over in the order they were written is what
    keeps a client able to read them.
    """
    device = await _own_device(session, user_id=user_id, device_id=device_id)
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
