"""What the transport accepts and returns.

Every key and every payload crosses this boundary as base64 in a string. The
server never interprets any of it: a payload is bytes it stores until somebody
collects them, and a key is bytes it hands to whoever is allowed to ask.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

#: A Curve25519 or Ed25519 public key is 32 bytes, which is 44 base64
#: characters. The bound is on the encoded form because that is what arrives.
KEY_B64_LENGTH = 44

#: One message. Anything larger is an attachment, which travels out of band.
MAX_PAYLOAD_BYTES = 64 * 1024
#: Base64 costs four characters per three bytes, plus padding.
MAX_PAYLOAD_B64 = (MAX_PAYLOAD_BYTES + 2) // 3 * 4

#: How many prekeys a device may publish. A client tops up toward this.
MAX_ONE_TIME_KEYS = 100

#: How many accounts may be on one group conversation.
#:
#: Fan-out means one ciphertext copy per destination device, so a message costs
#: its sender roughly (members x devices) KiB to upload. At 40 members and three
#: devices each that is ~119 KiB, which is about the most a line of text should
#: cost on mobile data. The number is above ordinary use on purpose -- a group
#: this size is already past where a direct message is the right thing.
MAX_GROUP_MEMBERS = 40


class DmOneTimeKeyUpload(BaseModel):
    key_id: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=1, max_length=KEY_B64_LENGTH)


class DmDeviceRegistration(BaseModel):
    identity_key: str = Field(min_length=1, max_length=KEY_B64_LENGTH)
    fingerprint_key: str = Field(min_length=1, max_length=KEY_B64_LENGTH)
    #: The reusable last-resort key, so a sender who arrives after the pool is
    #: drained can still open a session.
    fallback_key: DmOneTimeKeyUpload
    one_time_keys: list[DmOneTimeKeyUpload] = Field(
        default_factory=list, max_length=MAX_ONE_TIME_KEYS
    )
    # No label here. It is derived at registration from the request's own
    # user-agent, so it is a fact about the connection rather than a string the
    # client chose -- which is what the device list is more useful for, and what
    # keeps a name field out of a request body.


class DmOneTimeKeyBatch(BaseModel):
    device_id: uuid.UUID
    one_time_keys: list[DmOneTimeKeyUpload] = Field(
        min_length=1, max_length=MAX_ONE_TIME_KEYS
    )


class DmDeviceRead(BaseModel):
    """One of the caller's own devices, for the Security page."""

    id: uuid.UUID
    #: This device's own public identity key. Needed to recognise a message
    #: arriving from one of the account's other clients, and public by nature.
    identity_key: str
    fingerprint_key: str
    label: str | None
    created_at: datetime
    last_seen_at: datetime
    #: How many unclaimed prekeys it has left, so the client knows to top up.
    one_time_key_count: int


class DmDevicesResponse(BaseModel):
    devices: list[DmDeviceRead]


class DmSessionKey(BaseModel):
    """What a sender needs to open a session with one device."""

    device_id: uuid.UUID
    identity_key: str
    fingerprint_key: str
    #: Absent only if the device published nothing at all, which a registered
    #: device cannot do — a fallback key is required at registration.
    one_time_key: DmOneTimeKeyUpload | None = None


class DmOwnSessionKeysRequest(BaseModel):
    """Which device is asking, so it is left out of its own answer."""

    device_id: uuid.UUID


class DmSessionKeysResponse(BaseModel):
    user_id: int
    devices: list[DmSessionKey]


class DmSafetyNumberResponse(BaseModel):
    """Both parties' fingerprints, so the client can render the comparison."""

    user_id: int
    their_fingerprints: list[str]
    my_fingerprints: list[str]


class DmConversationCreate(BaseModel):
    user_id: int = Field(ge=1)


class DmGroupCreate(BaseModel):
    #: Everybody else on it. The caller is on it by proposing it, and is not
    #: named here.
    user_ids: list[int] = Field(min_length=2, max_length=MAX_GROUP_MEMBERS)


class DmRosterCheckRequest(BaseModel):
    #: The roster as it stands while somebody is still choosing names. The
    #: caller is counted but not named, the same as when it is proposed.
    user_ids: list[int] = Field(max_length=MAX_GROUP_MEMBERS * 2)


class DmRosterCheckResponse(BaseModel):
    """Whether this roster could be proposed, and what is wrong if not.

    Asked while the roster is being built rather than only when it is
    submitted, so the answer arrives while somebody can still drop a name.
    """

    #: Two accounts on the roster that cannot message each other. Empty when
    #: there is no such pair. Only the first is reported -- the fix for one is
    #: the fix for the next, and listing every pair would name accounts the
    #: caller would then be comparing against each other.
    unreachable_pair: list[int] = []
    #: How many accounts one conversation may carry, so the client can say so
    #: rather than hard-code it.
    max_members: int = MAX_GROUP_MEMBERS
    #: Whether the roster as it stands is past that.
    too_large: bool = False


class DmConversationRead(BaseModel):
    id: uuid.UUID
    #: For a pair, the other party. For a group, the lowest member id that is
    #: not the caller — kept so a client written before groups renders something
    #: rather than failing on a missing field. A client that knows about groups
    #: reads ``member_ids``.
    other_user_id: int
    created_at: datetime
    #: ``direct`` or ``group``.
    kind: str = "direct"
    #: Everybody on it except the caller, whether or not they have answered.
    #: Who has and has not is deliberately absent: a roster is what somebody
    #: agrees to, and reporting who is still deciding would put each invitee's
    #: hesitation in front of the others.
    member_ids: list[int] = []
    #: The same people as handles, in the same order, so a thread can be named
    #: by who is on it. Sent rather than looked up, because a group needs no
    #: accepted grant between every pair and the client may know nothing about
    #: somebody it is nonetheless in a conversation with. It discloses nothing
    #: a member of this conversation does not already have: the bell line and
    #: the push name the same people.
    member_handles: list[str] = []
    #: Whether the caller has answered their own invitation. False on every
    #: conversation a pair opens, because both sides agreed before it existed.
    pending: bool = False


class DmConversationsResponse(BaseModel):
    conversations: list[DmConversationRead]


class DmOutboundMessage(BaseModel):
    recipient_device_id: uuid.UUID
    #: Olm's own framing: 0 is a pre-key message, 1 continues a session.
    message_type: int = Field(ge=0, le=1)
    payload: str = Field(min_length=1, max_length=MAX_PAYLOAD_B64)


class DmSendRequest(BaseModel):
    messages: list[DmOutboundMessage] = Field(min_length=1, max_length=64)
    #: Deliver without a bell line. The server cannot read what it carries, so
    #: only the sender can say that this one is not news to anybody -- a client
    #: reporting that it collected or read something, rather than a person
    #: saying it. The recipient's tabs are still woken, because a device that
    #: is not told has nothing to collect.
    silent: bool = False
    #: Wake this account's *own* other installations with a push, not just the
    #: tabs that happen to be open. For the one thing a device sends its owner
    #: that a person has to get up and answer -- a new install asking to be sent
    #: the history it arrived without. The far device has to be opened by
    #: somebody before it can reply, and a websocket frame does not open it.
    #:
    #: Only the sender can say this, for the same reason only the sender can say
    #: ``silent``: the server cannot read what it carries. It says "worth
    #: waking", never what for, and the push that results names nothing.
    wake_own_devices: bool = False


class DmSendResponse(BaseModel):
    #: How many messages the server took from the sender -- which is all of
    #: them, or the request failed. Deliberately not what was written and
    #: deliberately not per-recipient: what reached whom is not something the
    #: sender is told, and a count that moved would be telling them.
    accepted: int
    #: Members whose mailbox was too full to take this. Named because a full
    #: mailbox is a fact about capacity that the sender can act on -- send it
    #: again later, or say something out of band. Nothing here ever reports a
    #: copy that was dropped for any other reason.
    queue_full_for: list[int] = []


class DmQueueItemRead(BaseModel):
    id: int
    conversation_id: uuid.UUID
    message_type: int
    payload: str
    created_at: datetime


class DmQueueResponse(BaseModel):
    items: list[DmQueueItemRead]


class DmQueueAck(BaseModel):
    device_id: uuid.UUID
    message_ids: list[int] = Field(min_length=1, max_length=500)
