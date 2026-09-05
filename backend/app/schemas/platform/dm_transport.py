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


class DmConversationRead(BaseModel):
    id: uuid.UUID
    other_user_id: int
    created_at: datetime


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


class DmSendResponse(BaseModel):
    #: How many rows were written. Deliberately not per-recipient: what reached
    #: whom is not something the sender is told.
    accepted: int


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
