"""An app that asks for tokens, for the suites that exercise the token endpoint
and the routes an installation token reaches.

Holds the app's two keypairs (RSA and P-256), the key set its registration
publishes, the client assertion it signs, and an install set up the way a
community sets one up: placed in an initiative, granted scopes by its seat,
and registered by the operator.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.document import Document
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing.factories import (
    create_app_service_registration,
    create_guild_app,
    create_initiative,
)
from app.testing.routing import route_as
from app.testing.schema_harness import route_session_to_guild

__all__ = [
    "CLIENT",
    "EC_KID",
    "LISTING",
    "RSA_KID",
    "InstalledApp",
    "client_jwks",
    "install_app",
    "mint_client_assertion",
    "share_with_members",
]

CLIENT = "tests.token-client"
LISTING = "TOKENCLIENT001"
RSA_KID = "token-client-rsa-1"
EC_KID = "token-client-ec-1"

_rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ec_key = ec.generate_private_key(ec.SECP256R1())


def client_jwks() -> dict[str, Any]:
    """The key set the app's registration publishes: one RSA key, one P-256."""
    rsa_entry = json.loads(RSAAlgorithm.to_jwk(_rsa_key.public_key()))
    rsa_entry["kid"] = RSA_KID
    ec_entry = json.loads(ECAlgorithm.to_jwk(_ec_key.public_key()))
    ec_entry["kid"] = EC_KID
    return {"keys": [rsa_entry, ec_entry]}


def mint_client_assertion(
    *,
    audience: str,
    key: str = "rsa",
    client_id: str = CLIENT,
    kid: Optional[str] = None,
    algorithm: Optional[str] = None,
    issued_at: Optional[float] = None,
    lifetime: int = 60,
    jti: Optional[str] = None,
    subject: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """A client assertion signed by one of the app's keys.

    ``key`` picks the signing key; ``kid`` and ``algorithm`` default to that
    key's own, and either may be set to something else to make the header
    disagree with the key. ``extra`` adds claims, as a member grant's
    ``installation`` and ``purpose``.
    """
    private = _rsa_key if key == "rsa" else _ec_key
    default_kid = RSA_KID if key == "rsa" else EC_KID
    default_alg = "RS256" if key == "rsa" else "ES256"
    iat = int(time.time() if issued_at is None else issued_at)
    claims = {
        "iss": client_id,
        "sub": client_id if subject is None else subject,
        "aud": audience,
        "jti": jti or secrets.token_urlsafe(16),
        "iat": iat,
        "exp": iat + lifetime,
        **(extra or {}),
    }
    return jwt.encode(
        claims,
        private,
        algorithm=algorithm or default_alg,
        headers={"kid": kid or default_kid, "typ": "JWT"},
    )


@dataclass
class InstalledApp:
    """What a test names: the seat, the community, the install, the initiative
    it is placed in and one it is not."""

    seat: Any
    app: GuildApp
    placed: Any
    unplaced: Any

    @property
    def guild(self) -> Any:
        return self.seat.guild


async def install_app(
    session: AsyncSession,
    acting_user: Any,
    role_session: Any,
    *,
    granted: Sequence[str],
    client_id: str = CLIENT,
    listing_uid: str = LISTING,
    register: bool = True,
    enabled: bool = True,
) -> InstalledApp:
    """An install of ``client_id``'s listing, placed in one of two
    initiatives and granted ``granted`` by the community's seat, with the
    operator's registration publishing :func:`client_jwks`."""
    seat = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
    unplaced = await create_initiative(session, seat.guild, seat.user, name="B")
    app = await create_guild_app(
        session,
        seat.guild,
        seat.user,
        definition={
            "app_kind": "service",
            "service": {"public_id": client_id, "protocol": 1},
        },
        listing_uid=listing_uid,
    )
    if register:
        await create_app_service_registration(
            session,
            public_id=client_id,
            listing_uid=listing_uid,
            enabled=enabled,
            jwks=client_jwks(),
        )

    await route_session_to_guild(session, seat.guild.id)
    session.add(AppPlacement(install_id=app.id, initiative_id=seat.initiative.id))
    await session.commit()

    if granted:
        s = await role_session("app_user")
        await route_as(s, user_id=seat.user.id, guild_id=seat.guild.id)
        row = (await s.exec(select(GuildApp).where(GuildApp.id == app.id))).one()
        row.granted_scopes = list(granted)
        s.add(row)
        await s.commit()
    return InstalledApp(seat=seat, app=app, placed=seat.initiative, unplaced=unplaced)


async def share_with_members(
    session: AsyncSession, document: Document, initiative_id: int
) -> None:
    """Share ``document`` with every member of its initiative, which an
    install placed there counts as."""
    session.add(
        ResourceGrant(
            resource_type=Tool.document.value,
            resource_id=document.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            initiative_id=initiative_id,
        )
    )
    await session.commit()
