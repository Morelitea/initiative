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
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import seal_install_token
from app.core.app_scopes import ALL_SCOPES

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
    "assert_names_nobody",
    "client_jwks",
    "install_app",
    "install_headers",
    "lift_person_and_guild_ids",
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
    requested: Optional[Sequence[str]] = None,
) -> InstalledApp:
    """An install of ``client_id``'s listing, placed in one of two
    initiatives and granted ``granted`` by the community's seat, with the
    operator's registration publishing :func:`client_jwks`.

    The pinned manifest requests ``requested``, every scope by default, so
    the grant is what decides what a token carries."""
    seat = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
    unplaced = await create_initiative(session, seat.guild, seat.user, name="B")
    app = await create_guild_app(
        session,
        seat.guild,
        seat.user,
        definition={
            "app_kind": "service",
            "service": {
                "public_id": client_id,
                "protocol": 1,
                "scopes": list(ALL_SCOPES if requested is None else requested),
            },
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


def install_headers(
    installed: InstalledApp,
    scopes: Sequence[str],
    *,
    initiative_id: Optional[int] = None,
    install_id: Optional[int] = None,
    client_id: str = CLIENT,
) -> dict[str, str]:
    """The ``Authorization`` header of an installation token for ``installed``,
    carrying ``scopes`` and narrowed to ``initiative_id`` when one is given."""
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=install_id if install_id is not None else installed.app.id,
        client_id=client_id,
        scopes=frozenset(scopes),
        initiative_id=initiative_id,
    )
    return {"Authorization": f"Bearer {token}"}


#: Where people's and communities' ids start in a test that looks for them in a
#: response: far above any id another table will reach in one test, so finding
#: the digits anywhere in a body means somebody's id is there.
_PERSON_ID_FLOOR = 7_000_000
_GUILD_ID_FLOOR = 8_000_000


async def lift_person_and_guild_ids(session: AsyncSession) -> None:
    """Start the ids of the people and communities made after this far above
    every other row id, so :func:`assert_names_nobody` can tell one in a
    response wherever it sits — a field, a nested object, a URL. Call it
    before creating anybody."""
    offset = secrets.randbelow(100_000)
    await session.exec(
        text("SELECT setval('public.users_id_seq', :v)"),
        params={"v": _PERSON_ID_FLOOR + offset},
    )
    await session.exec(
        text("SELECT setval('public.guilds_id_seq', :v)"),
        params={"v": _GUILD_ID_FLOOR + offset},
    )
    await session.commit()


def assert_names_nobody(body: str, ids: Sequence[int]) -> None:
    """Fail if any of ``ids`` — people's or a community's, lifted by
    :func:`lift_person_and_guild_ids` — appears anywhere in ``body``."""
    found = [value for value in ids if str(value) in body]
    assert not found, f"the response names {found}: {body[:2000]}"
