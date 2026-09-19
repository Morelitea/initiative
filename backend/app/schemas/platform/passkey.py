"""Payloads for the account's passkeys."""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel

#: The longest name a passkey may be given. Mirrors the service's cap.
NAME_MAX_LENGTH = 64


class PasskeyRead(SanitizedBaseModel):
    """One credential, as its holder sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    #: Whether the credential is synced by a password manager, so losing the
    #: device does not lose the key.
    backed_up: bool
    #: Whether the ceremony that made it proved the person as well as the
    #: device — a PIN, a fingerprint, a face.
    user_verified: bool
    #: How the authenticator can be reached — usb, nfc, ble, internal, hybrid.
    transports: list[str] = Field(default_factory=list)
    #: The authenticator model's identifier, when it reported one.
    aaguid: Optional[str] = None


class PasskeyList(SanitizedBaseModel):
    """What the account holds, for the settings surface."""

    passkeys: list[PasskeyRead] = Field(default_factory=list)
    #: Whether this account holds a password the passkey routes will re-check.
    #: The form asks for one only when there is one to give.
    password_required: bool = True
    #: The most passkeys one account may hold.
    limit: int


class PasskeyRegisterStart(SanitizedBaseModel):
    """Beginning a registration. The password is re-checked here, as it is for a
    password change; an account with no usable password sends nothing."""

    current_password: Optional[str] = None


class PasskeyRegistrationOptions(SanitizedBaseModel):
    """What the browser's credential API is handed, as the library renders it."""

    #: ``PublicKeyCredentialCreationOptionsJSON`` — passed to the browser as is.
    options: dict[str, Any]


class PasskeyRegisterFinish(SanitizedBaseModel):
    """The browser's answer, and the name the person gives the credential."""

    #: ``RegistrationResponseJSON`` — the credential as the browser returned it.
    credential: dict[str, Any]
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class PasskeyRename(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class PasskeyRemove(SanitizedBaseModel):
    """Removing a way in asks for the password, where there is one."""

    current_password: Optional[str] = None
