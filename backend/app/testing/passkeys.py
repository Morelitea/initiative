"""Standing in for an authenticator.

A WebAuthn ceremony needs a browser and a key, and a test has neither. What is
here is the pair of things a test does instead: the shape the browser would
hand back, and a stand-in for the library's own check of it — so a test can say
what a ceremony proved without proving it.

The signature is never real, so these are for the rules around a ceremony:
which challenge answers which request, whose credential it is, what a refusal
writes down. A test of the cryptography would be a test of ``py_webauthn``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from webauthn.helpers import bytes_to_base64url

from app.models.platform.user import User
from app.models.platform.user_passkey import UserPasskey
from app.services.auth import passkeys as passkey_service
from sqlmodel.ext.asyncio.session import AsyncSession

#: Where the browser says it was. The ceremonies check this against the
#: deployment's own address, which the test settings put here.
TEST_ORIGIN = "http://localhost:5173"


def assertion_for(
    challenge: str,
    *,
    credential_id: str = "credential-one",
    origin: str = TEST_ORIGIN,
) -> dict[str, Any]:
    """What the browser hands back for a sign-in, with the challenge inside the
    client data it signed — which is where the server reads it from."""
    raw_id = bytes_to_base64url(credential_id.encode())
    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": origin}
    ).encode()
    return {
        "id": raw_id,
        "rawId": raw_id,
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(client_data),
            "authenticatorData": bytes_to_base64url(b"authenticator"),
            "signature": bytes_to_base64url(b"signature"),
        },
    }


def stub_assertion(monkeypatch, *, backed_up: bool = False) -> None:
    """Stand in for the library's assertion check, reporting what a verified
    ceremony reports."""

    def verify(**kwargs):
        return SimpleNamespace(
            new_sign_count=kwargs["credential_current_sign_count"] + 1,
            credential_backed_up=backed_up,
            user_verified=True,
        )

    monkeypatch.setattr(
        passkey_service.webauthn, "verify_authentication_response", verify
    )


async def create_passkey(
    session: AsyncSession,
    user: User,
    *,
    credential_id: str = "credential-one",
    backed_up: bool = False,
    name: str = "Signing key",
) -> UserPasskey:
    """Give ``user`` a credential to answer with."""
    row = await passkey_service.store(
        session,
        user_id=user.id,
        registered=passkey_service.RegisteredCredential(
            credential_id=credential_id.encode(),
            public_key=b"public-key-bytes",
            sign_count=0,
            aaguid=None,
            user_verified=True,
            backed_up=backed_up,
            transports=["internal"],
        ),
        name=name,
    )
    await session.commit()
    return row
