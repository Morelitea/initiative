"""Where an installed app's service answers, served to a delegate.

An automation service acts on apps as well as on Initiative — it asks one to
open a GitHub issue the way it asks us to create a task — and to do that it has
to know where the app is. Only the registration says, and the registration is
operator wiring: an internal Service address on a cluster.

So this route hands it over on one condition and hides it from everybody else.
What is pinned here is that condition, both halves of it: the caller must have
arrived as a live delegate, and every way of not being one answers the same 404
as an app that does not exist.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.platform.guild import GuildRole
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing.delegation import (
    authorize_delegate,
    delegate_subject,
    install_delegate,
    mint_delegation_token,
    register_delegate,
)
from app.testing.factories import create_guild_app
from app.testing.schema_harness import route_session_to_guild

#: The app being asked about — not the delegate. Two registrations, because
#: the whole point is one app learning where a *different* one lives.
TARGET_PUBLIC_ID = "morelitea.github"
TARGET_LISTING_UID = "TESTGITHUB0001"
TARGET_BASE_URL = "http://initiative-github.svc.cluster.local:8080"


@pytest.fixture(autouse=True)
async def _enable_delegation(session: AsyncSession):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            config_module.settings,
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
            "-----BEGIN PRIVATE KEY-----",
        )
        await register_delegate(session)
        yield
    invalidate_registrations()


async def _register_target(session: AsyncSession, *, enabled: bool = True) -> None:
    """The app whose address is being asked for."""
    from app.models.platform.app_service_registration import (
        AppServiceRegistration,
        AppServiceStatus,
    )

    session.add(
        AppServiceRegistration(
            public_id=TARGET_PUBLIC_ID,
            listing_uid=TARGET_LISTING_UID,
            base_url=TARGET_BASE_URL,
            allowed_origins=[TARGET_BASE_URL],
            secret_encrypted=None,
            grants=[],
            delegation_jwks=None,
            enabled=enabled,
            status=AppServiceStatus.OK,
        )
    )
    await session.commit()
    invalidate_registrations()


async def _install_target(session: AsyncSession, guild, installer, **overrides):
    await route_session_to_guild(session, guild.id)
    return await create_guild_app(
        session,
        guild,
        installer,
        definition={
            "app_kind": "service",
            "service": {"public_id": TARGET_PUBLIC_ID},
        },
        listing_uid=TARGET_LISTING_UID,
        name="GitHub",
        **overrides,
    )


@pytest.fixture
async def scene(session: AsyncSession, acting_user):
    """A guild with the delegate installed and a member who authorized it.

    Built through ``acting_user`` so the member is a real one — membership and
    a first-party session included. Both are load-bearing here: a delegated
    call runs under the named member's own authorization, and one of these
    tests needs that member's browser session to be refused where their
    delegate's token is not.
    """
    actor = await acting_user(guild_role=GuildRole.admin)
    await install_delegate(session, actor.guild, creator=actor.user)
    await authorize_delegate(session, actor.guild, actor.user)
    subject = await delegate_subject(session, actor.guild, actor.user)
    return actor, subject


def _headers(subject: str, guild_id: int, jti: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_delegation_token(subject=subject, guild_id=guild_id, jti=jti)}"
    }


@pytest.mark.integration
async def test_a_live_delegate_is_told_where_the_app_answers(
    client: AsyncClient, session: AsyncSession, scene
):
    actor, subject = scene
    guild, installer = actor.guild, actor.user
    await _register_target(session)
    app = await _install_target(session, guild, installer)

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service",
        headers=_headers(subject, guild.id, "svc-ok-001"),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "public_id": TARGET_PUBLIC_ID,
        "base_url": TARGET_BASE_URL,
        "available": True,
    }


@pytest.mark.integration
async def test_the_answer_says_nothing_about_the_person(
    client: AsyncClient, session: AsyncSession, scene
):
    """The caller learns an address and the app's own id. Not who asked, not
    who installed it, and nothing that correlates a member across apps."""
    actor, subject = scene
    guild, installer = actor.guild, actor.user
    await _register_target(session)
    app = await _install_target(session, guild, installer)

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service",
        headers=_headers(subject, guild.id, "svc-shape-001"),
    )

    assert set(response.json()) == {"public_id", "base_url", "available"}
    assert subject not in response.text
    assert installer.email not in response.text


@pytest.mark.integration
async def test_a_switched_off_install_still_answers_and_says_so(
    client: AsyncClient, session: AsyncSession, scene
):
    """``available`` is a real answer rather than a 404.

    A caller that knows the app is switched off can park a run and say why. An
    address it cannot tell from a missing app leaves it guessing.
    """
    actor, subject = scene
    guild, installer = actor.guild, actor.user
    await _register_target(session)
    app = await _install_target(session, guild, installer, enabled=False)

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service",
        headers=_headers(subject, guild.id, "svc-disabled-001"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["available"] is False
    assert response.json()["base_url"] == TARGET_BASE_URL


@pytest.mark.integration
async def test_a_first_party_session_is_refused(
    client: AsyncClient, session: AsyncSession, scene
):
    """The address is not a member's to read.

    A signed-in guild admin can see the install in every other way; this one
    field is the operator's wiring, and a browser has no use for it.
    """
    actor, _subject = scene
    guild, installer = actor.guild, actor.user
    await _register_target(session)
    app = await _install_target(session, guild, installer)

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service", headers=actor.headers
    )

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize(
    "grants, enabled, case",
    [
        pytest.param((), True, "grant-withdrawn", id="delegate-without-the-grant"),
        pytest.param(
            ("delegation",), False, "switched-off", id="delegate-switched-off"
        ),
    ],
)
async def test_a_delegate_that_may_not_act_is_refused(
    client: AsyncClient, session: AsyncSession, scene, grants, enabled, case
):
    """An operator's edit ends the call, and it ends it before the route.

    The same rule decides which keys verify a delegate's tokens, so withdrawing
    the grant or switching the registration off leaves the token resolving to
    no key at all — it is not authenticated as a delegation, and the answer is
    the bare **401** that every refused delegation gets, not this route's 404.

    Asserted rather than assumed, because it is the difference between two
    kinds of protection. The route's own ``live_delegate`` check is defence in
    depth for exactly this case; what stops it here is the auth layer, one
    floor down, and a change that moved the address behind a different auth
    path would need to keep this property on purpose.
    """
    actor, subject = scene
    guild, installer = actor.guild, actor.user
    await _register_target(session)
    app = await _install_target(session, guild, installer)
    headers = _headers(subject, guild.id, f"svc-{case}")

    # Re-register the delegate with the operator's edit applied. Done after the
    # token is minted, because what is being tested is the check at use rather
    # than at issue.
    from sqlmodel import delete

    from app.models.platform.app_service_registration import AppServiceRegistration
    from app.testing.delegation import DELEGATE_PUBLIC_ID

    await session.exec(
        delete(AppServiceRegistration).where(
            AppServiceRegistration.public_id == DELEGATE_PUBLIC_ID
        )
    )
    await session.commit()
    await register_delegate(session, grants=grants, enabled=enabled)

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service", headers=headers
    )

    assert response.status_code == 401
    assert TARGET_BASE_URL not in response.text


@pytest.mark.integration
async def test_an_app_with_no_service_behind_it_has_no_address(
    client: AsyncClient, session: AsyncSession, scene
):
    """A tool instance or an embed is installed but has no container, so there
    is no address for one to be given."""
    actor, subject = scene
    guild, installer = actor.guild, actor.user
    await route_session_to_guild(session, guild.id)
    app = await create_guild_app(
        session,
        guild,
        installer,
        definition={"app_kind": "tool", "tool": "projects"},
        listing_uid="TESTTOOL000001",
        name="A tool",
    )

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service",
        headers=_headers(subject, guild.id, "svc-no-service-001"),
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_a_service_this_deployment_never_wired_up_has_no_address(
    client: AsyncClient, session: AsyncSession, scene
):
    """Installed here, but with no registration — so nothing it offers can be
    reached and there is no address to hand over."""
    actor, subject = scene
    guild, installer = actor.guild, actor.user
    app = await _install_target(session, guild, installer)

    response = await client.get(
        f"/api/v1/g/{guild.id}/apps/{app.id}/service",
        headers=_headers(subject, guild.id, "svc-unregistered-001"),
    )

    assert response.status_code == 404
