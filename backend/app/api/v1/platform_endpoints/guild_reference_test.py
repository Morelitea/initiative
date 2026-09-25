"""Naming one guild in a sector other than the caller's.

A reference is minted per sector, so two parties hold unrelated values for one
guild and only this deployment holds both. A service that has to reconcile two
of them asks here, presenting one of its own.

Most of what is asserted is what it refuses. The answer is another sector's
name, so the reaches that must not work are the subject: a caller with no
secret, a reference that is not the caller's own, and an app sector — which
belongs to one install and is the one translation that would let an app learn
another's names.

See ``history/opaque-identity-design.md`` §15.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.messages import BundledChannelMessages
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.marketplace.app_refs import ensure_app_guild_ref
from app.services.platform.identity_refs import ensure_ref
from app.testing import create_guild, create_guild_app, create_user

ROUTE = "/api/v1/app-platform/community-reference"
SECRET = "a-bundled-service-secret-for-tests"
#: The service this deployment ships, by the public id its registration carries.
BUNDLED_PUBLIC_ID = "acme.auto"


@pytest.fixture(autouse=True)
def _wired(monkeypatch):
    """An operator has named the bundled service and wired its secret."""
    monkeypatch.setattr(
        config_module.settings, "BUNDLED_SERVICE_PUBLIC_ID", BUNDLED_PUBLIC_ID
    )
    monkeypatch.setattr(config_module.settings, "BUNDLED_SERVICE_SHARED_SECRET", SECRET)


def _headers(body: bytes, *, secret: str = SECRET, at: int | None = None) -> dict:
    ts = str(at if at is not None else int(time.time()))
    message = f"POST\n{ROUTE}\n{ts}\n{hashlib.sha256(body).hexdigest()}"
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Initiative-Timestamp": ts,
        "X-Initiative-Signature": f"sha256={mac}",
    }


async def _ask(client: AsyncClient, payload: dict, **overrides):
    body = json.dumps(payload).encode()
    return await client.post(ROUTE, content=body, headers=_headers(body, **overrides))


async def _callers_own_ref(session: AsyncSession, guild) -> str:
    """A reference minted at the bundled service's own install."""
    # A user is a public row, so it is made before the session is routed into
    # the guild to write the install.
    installer = await create_user(session)
    app = await create_guild_app(
        session,
        guild,
        installer,
        definition={"app_kind": "service", "service": {"public_id": BUNDLED_PUBLIC_ID}},
        name="Bundled",
    )
    await session.commit()
    return await ensure_app_guild_ref(guild_id=guild.id, app_install_id=app.id)


async def test_it_names_the_same_guild_in_the_sector_asked_for(
    client: AsyncClient, session: AsyncSession
):
    """The one operation. Asserted against what that sector actually holds,
    because a different value would leave the two parties writing past each
    other — which is the fault this exists to end."""
    user = await create_user(session, email="translate@example.com")
    guild = await create_guild(session, creator=user)
    expected = await ensure_ref(
        session,
        entity_type=IdentityEntity.guild,
        entity_id=guild.id,
        purpose=IdentityPurpose.billing,
    )
    await session.commit()
    own = await _callers_own_ref(session, guild)

    response = await _ask(client, {"guild_ref": own, "purpose": "billing"})

    assert response.status_code == 200, response.text
    assert response.json() == {"purpose": "billing", "guild_ref": expected}
    assert response.json()["guild_ref"] != own


async def test_a_reference_that_is_not_the_callers_own_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """Resolving says which install minted a reference; this says that install
    is the caller's. A value minted somewhere else resolves fine and is not an
    answer to this question."""
    user = await create_user(session, email="not-mine@example.com")
    guild = await create_guild(session, creator=user)
    await ensure_ref(
        session,
        entity_type=IdentityEntity.guild,
        entity_id=guild.id,
        purpose=IdentityPurpose.billing,
    )
    await session.commit()
    # A reference for an install that is not the bundled service's.
    someone_elses = await ensure_app_guild_ref(guild_id=guild.id, app_install_id=98765)

    response = await _ask(client, {"guild_ref": someone_elses, "purpose": "billing"})

    assert response.status_code == 404
    assert response.json()["detail"] == BundledChannelMessages.UNKNOWN_GUILD


@pytest.mark.parametrize("purpose", ["app", "webhook"])
async def test_a_sector_inside_a_guild_is_not_answerable(
    client: AsyncClient, session: AsyncSession, purpose: str
):
    """Both name something inside a guild — an install, a subscription — and
    take that thing's id as well. A caller holding one guild reference has no
    way to say which one it means, so neither is asked for here.

    Refused rather than searched: looking without the id matches references
    that carry none, which is none of these."""
    user = await create_user(session, email=f"sector-{purpose}@example.com")
    guild = await create_guild(session, creator=user)
    own = await _callers_own_ref(session, guild)

    response = await _ask(client, {"guild_ref": own, "purpose": purpose})

    assert response.status_code == 400
    assert response.json()["detail"] == BundledChannelMessages.SECTOR_NOT_ANSWERABLE


async def test_a_sector_that_has_never_named_the_guild_is_not_minted_one(
    client: AsyncClient, session: AsyncSession
):
    """Reporting which entity a sector already names is one thing; letting a
    party outside it create a row there is another."""
    from app.services.platform.identity_refs import existing_ref

    user = await create_user(session, email="never-named@example.com")
    guild = await create_guild(session, creator=user)
    own = await _callers_own_ref(session, guild)

    response = await _ask(client, {"guild_ref": own, "purpose": "billing"})

    assert response.status_code == 404
    assert response.json()["detail"] == BundledChannelMessages.NO_SUCH_NAME
    # And asking did not put one there.
    assert (
        await existing_ref(
            entity_type=IdentityEntity.guild,
            entity_id=guild.id,
            purpose=IdentityPurpose.billing,
        )
        is None
    )


async def test_a_caller_without_the_secret_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """The secret has one holder, and it is the whole of who may ask."""
    user = await create_user(session, email="no-secret@example.com")
    guild = await create_guild(session, creator=user)
    own = await _callers_own_ref(session, guild)

    response = await _ask(
        client, {"guild_ref": own, "purpose": "billing"}, secret="not-the-secret"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == BundledChannelMessages.BAD_SIGNATURE


async def test_a_signature_from_another_moment_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """Bound to a timestamp inside a window, so a captured envelope stops
    working rather than working forever."""
    user = await create_user(session, email="stale@example.com")
    guild = await create_guild(session, creator=user)
    own = await _callers_own_ref(session, guild)

    response = await _ask(
        client,
        {"guild_ref": own, "purpose": "billing"},
        at=int(time.time()) - 3600,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == BundledChannelMessages.STALE_TIMESTAMP


async def test_a_deployment_that_ships_no_bundled_service_is_inert(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """503 rather than 403: unconfigured is this deployment's own gap, and
    retryable, which is what the rest of this surface answers too."""
    monkeypatch.setattr(config_module.settings, "BUNDLED_SERVICE_SHARED_SECRET", None)

    response = await _ask(client, {"guild_ref": "gapp_whatever", "purpose": "billing"})

    assert response.status_code == 503
    assert response.json()["detail"] == BundledChannelMessages.NOT_CONFIGURED


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"not json at all", id="not-json"),
        pytest.param(b'{"purpose": "billing"}', id="no-reference"),
        pytest.param(
            b'{"guild_ref": "gapp_x", "purpose": "sideways"}', id="no-such-sector"
        ),
    ],
)
async def test_a_signed_body_of_the_wrong_shape_is_answered(
    client: AsyncClient, payload: bytes
):
    """Signed and still unreadable. A caller that got the envelope right and
    the body wrong is told so, rather than being handed a fault to retry."""
    response = await client.post(ROUTE, content=payload, headers=_headers(payload))

    assert response.status_code == 422
    assert response.json()["detail"] == BundledChannelMessages.INVALID_PAYLOAD


# ---------------------------------------------------------------------------
# An installation token, for an app the registry gave a sector
# ---------------------------------------------------------------------------

SECTORED_ID = "morelitea.auto"
SECTORED_UID = "MRXAVT00000001"


@pytest.fixture
def shipped_root(monkeypatch, tmp_path):
    """This build ships a root, and nothing replaces it."""
    from app.services.marketplace import tuf_registry
    from app.testing.tuf_repository import TufRepository

    root = tmp_path / "root.json"
    root.write_bytes(TufRepository().root_bytes())
    monkeypatch.setattr(tuf_registry, "BUILTIN_ROOT_PATH", root)
    monkeypatch.setattr(config_module.settings, "MARKETPLACE_REGISTRY_ROOT", None)
    return root


async def _sectored_install(session: AsyncSession, **registration):
    """A guild with the sectored app installed, a billing name for the guild,
    and an installation token for the install."""
    from app.core.app_access_token import seal_install_token
    from app.testing import create_app_service_registration, create_guild_app

    fields = {
        "source": "registry",
        "reference_sectors": ["billing"],
        "root_is_builtin": True,
        **registration,
    }
    await create_app_service_registration(
        session, public_id=SECTORED_ID, listing_uid=SECTORED_UID, **fields
    )
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    app = await create_guild_app(
        session,
        guild,
        user,
        definition={
            "app_kind": "service",
            "service": {"public_id": SECTORED_ID, "protocol": 1},
            "features": [],
        },
        listing_uid=SECTORED_UID,
    )
    billing = await ensure_ref(
        session,
        entity_type=IdentityEntity.guild,
        entity_id=guild.id,
        purpose=IdentityPurpose.billing,
    )
    await session.commit()
    token, _exp = seal_install_token(
        guild_id=guild.id,
        install_id=app.id,
        client_id=SECTORED_ID,
        scopes=frozenset(),
        initiative_id=None,
        user_id=None,
        purpose=None,
    )
    return guild, app, billing, {"Authorization": f"Bearer {token}"}


async def test_a_token_whose_registration_carries_the_sector_is_answered(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    _guild, _app, billing, headers = await _sectored_install(session)

    response = await client.post(ROUTE, json={"purpose": "billing"}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"purpose": "billing", "guild_ref": billing}


async def test_a_token_naming_its_own_reference_for_the_guild_is_answered(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    guild, app, billing, headers = await _sectored_install(session)
    own = await ensure_app_guild_ref(guild_id=guild.id, app_install_id=app.id)

    response = await client.post(
        ROUTE, json={"purpose": "billing", "guild_ref": own}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["guild_ref"] == billing


async def test_a_token_naming_another_guild_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    _guild, _app, _billing, headers = await _sectored_install(session)
    other = await create_guild(session, creator=await create_user(session))
    await session.commit()
    elsewhere = await ensure_app_guild_ref(guild_id=other.id, app_install_id=98765)

    response = await client.post(
        ROUTE, json={"purpose": "billing", "guild_ref": elsewhere}, headers=headers
    )

    assert response.status_code == 404


async def test_a_token_without_the_sector_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    _guild, _app, _billing, headers = await _sectored_install(
        session, reference_sectors=[]
    )

    response = await client.post(ROUTE, json={"purpose": "billing"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == BundledChannelMessages.SECTOR_NOT_ANSWERABLE


async def test_a_sector_from_an_operators_registration_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    _guild, _app, _billing, headers = await _sectored_install(
        session, source="operator"
    )

    response = await client.post(ROUTE, json={"purpose": "billing"}, headers=headers)

    assert response.status_code == 403


async def test_a_sector_is_refused_under_a_replaced_root(
    client: AsyncClient, session: AsyncSession, shipped_root, monkeypatch, tmp_path
):
    """A registration written while the shipped root was in use carries the
    flag; replacing the root afterwards still ends the sector."""
    from app.testing.tuf_repository import TufRepository

    _guild, _app, _billing, headers = await _sectored_install(session)
    replaced = tmp_path / "replaced.json"
    replaced.write_bytes(TufRepository().root_bytes())
    monkeypatch.setattr(
        config_module.settings, "MARKETPLACE_REGISTRY_ROOT", str(replaced)
    )

    response = await client.post(ROUTE, json={"purpose": "billing"}, headers=headers)

    assert response.status_code == 403


async def test_a_sector_recorded_under_another_root_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    _guild, _app, _billing, headers = await _sectored_install(
        session, root_is_builtin=False
    )

    response = await client.post(ROUTE, json={"purpose": "billing"}, headers=headers)

    assert response.status_code == 403


async def test_a_token_that_does_not_verify_is_refused(
    client: AsyncClient, session: AsyncSession, shipped_root
):
    await _sectored_install(session)

    response = await client.post(
        ROUTE,
        json={"purpose": "billing"},
        headers={"Authorization": "Bearer not-a-token"},
    )

    # Not an access token, so this is the bundled channel, which refuses an
    # unsigned request.
    assert response.status_code == 403
