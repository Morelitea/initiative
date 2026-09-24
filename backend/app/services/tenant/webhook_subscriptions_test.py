"""A subscription's reach is the scope it names.

Delivery used to read the change log as the account that registered the
subscription, which made ``created_by`` an authorization principal and made a
subscription stop working when that person's standing changed — silently, since
the poller stood down before attempting a delivery and so never counted a
failure. ``history/webhook-scope-not-principal-design.md`` has the argument for
why that principal decided nothing the declared scope had not already decided.

What the tests below hold is the replacement: the scope decides, the scope is
all that decides, and an account going away does not end a community's
integration. What an automation may *do* with a delivery is a separate gate in
a separate place — a delegation naming a member, re-read on every call — and is
not exercised here.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.testing.schema_harness import route_session_to_guild

pytestmark = [pytest.mark.integration, pytest.mark.service]


async def _subscribe(
    session: AsyncSession, *, guild_id: int, user_id: int, initiative_id: int | None
) -> None:
    await route_session_to_guild(session, guild_id)
    now = datetime.now(timezone.utc)
    session.add(
        WebhookSubscription(
            initiative_id=initiative_id,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()


def _collector(monkeypatch, poller) -> list[dict]:
    sent: list[dict] = []

    async def _accept(*, target_url, secret, envelope):
        sent.append(envelope)
        return True

    monkeypatch.setattr(poller, "deliver", _accept)
    return sent


async def test_delivery_outlives_the_account_that_registered_it(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """The change this is all for: erasing the registrant is not a decision
    about the community's integration, so it does not end one."""
    from app.services.platform import users as user_service
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id, user_id, project = a.guild.id, a.user.id, a.project
    await _subscribe(session, guild_id=guild_id, user_id=user_id, initiative_id=None)

    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    await user_service.hard_delete_user(system, user_id)
    session.expunge_all()
    await create_task(session, project)
    session.expunge_all()

    await poller._drain_guild(system, guild_id, now=datetime.now(timezone.utc))
    assert sent, "an erased registrant ended a subscription that should outlive them"


async def test_erasure_leaves_the_subscription_alone(
    session: AsyncSession, role_session, acting_user
):
    """And the row is untouched — no account's lifecycle reaches it."""
    from app.services.platform import users as user_service

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    guild_id, user_id = a.guild.id, a.user.id
    await _subscribe(session, guild_id=guild_id, user_id=user_id, initiative_id=None)

    await user_service.hard_delete_user(await role_session("app_admin"), user_id)

    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    rows = list(await session.exec(select(WebhookSubscription)))
    assert len(rows) == 1
    assert rows[0].active is True
    assert rows[0].created_by == user_id


async def test_an_initiative_subscription_hears_only_that_initiative(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """The scope is the decision, so a second initiative's changes are not in
    the batch — with nobody's membership consulted to work that out."""
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task
    from app.testing.factories import create_initiative, create_project

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id = a.guild.id
    other = await create_initiative(session, a.guild, a.user)
    other_project = await create_project(session, other, a.user)

    await _subscribe(
        session, guild_id=guild_id, user_id=a.user.id, initiative_id=a.initiative.id
    )
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    await create_task(session, a.project)
    session.expunge_all()
    await create_task(session, other_project)
    session.expunge_all()

    await poller._drain_guild(system, guild_id, now=datetime.now(timezone.utc))

    named = {
        change["initiative_id"] for envelope in sent for change in envelope["changes"]
    }
    assert named == {a.initiative.id}


async def test_a_community_subscription_hears_every_initiative(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """Naming no initiative means the community's changes, which is what a
    guild admin registering one is asking for."""
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task
    from app.testing.factories import create_initiative, create_project

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id = a.guild.id
    other = await create_initiative(session, a.guild, a.user)
    other_project = await create_project(session, other, a.user)

    await _subscribe(session, guild_id=guild_id, user_id=a.user.id, initiative_id=None)
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    await create_task(session, a.project)
    session.expunge_all()
    await create_task(session, other_project)
    session.expunge_all()

    await poller._drain_guild(system, guild_id, now=datetime.now(timezone.utc))

    named = {
        change["initiative_id"] for envelope in sent for change in envelope["changes"]
    }
    assert named == {a.initiative.id, other.id}


# ---------------------------------------------------------------------------
# A subscription an installed app registered
# ---------------------------------------------------------------------------


def _install_context(**overrides):
    from app.db.guild_standing import InstallContext

    defaults = dict(
        guild_id=1,
        install_id=4,
        client_id="tests.app",
        token_scopes=frozenset({"documents:read"}),
        live=True,
        member_initiatives=(11, 12),
        install_read=("documents",),
    )
    defaults.update(overrides)
    return InstallContext(**defaults)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "event_types", "initiative_id"),
    [
        pytest.param({}, ["documents.created"], None, id="community-wide"),
        pytest.param({}, ["documents.updated"], 12, id="a-placed-initiative"),
        pytest.param(
            {"scope_initiative_id": 11}, ["documents.deleted"], 11, id="narrowed"
        ),
        pytest.param(
            {"install_read": ("documents", "projects")},
            ["documents.created", "tasks.created"],
            None,
            id="every-tool-held",
        ),
    ],
)
def test_an_install_may_subscribe_within_its_standing(
    overrides, event_types, initiative_id
):
    from app.services.tenant.webhook_subscriptions import assert_install_may_subscribe

    assert_install_may_subscribe(
        _install_context(**overrides),
        event_types=event_types,
        initiative_id=initiative_id,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "event_types", "initiative_id"),
    [
        pytest.param({}, ["tasks.created"], None, id="tool-scope-missing"),
        pytest.param(
            {}, ["documents.created", "tasks.created"], None, id="one-type-uncovered"
        ),
        pytest.param({}, ["apps.created"], None, id="no-scope-reaches-it"),
        pytest.param(
            {"scope_initiative_id": 11},
            ["documents.created"],
            None,
            id="narrowed-community-wide",
        ),
        pytest.param(
            {"scope_initiative_id": 11},
            ["documents.created"],
            12,
            id="narrowed-other-initiative",
        ),
        pytest.param({}, ["documents.created"], 13, id="not-placed"),
    ],
)
def test_an_install_may_not_subscribe_beyond_its_standing(
    overrides, event_types, initiative_id
):
    from app.core.messages import AppMessages
    from app.services.tenant.webhook_subscriptions import (
        WebhookSubscriptionScopeError,
        assert_install_may_subscribe,
    )

    with pytest.raises(WebhookSubscriptionScopeError) as refused:
        assert_install_may_subscribe(
            _install_context(**overrides),
            event_types=event_types,
            initiative_id=initiative_id,
        )
    assert refused.value.code == AppMessages.SCOPE_REQUIRED


_HOOK = "https://app.example.test/hook"


async def _install_subscribes(role_session, install, *, initiative_id=None):
    """The install registers a subscription to documents as its community."""
    from app.db.install_standing_test import _route
    from app.schemas.tenant.webhook_subscription import WebhookSubscriptionCreate
    from app.services.tenant.webhook_subscriptions import create_install_subscription

    s, context = await _route(role_session, install, ["documents:write"])
    row, _secret = await create_install_subscription(
        s,
        context=context,
        payload=WebhookSubscriptionCreate(
            target_url=_HOOK,
            event_types=["documents.created"],
            initiative_id=initiative_id,
        ),
    )
    return row


async def test_an_install_registers_a_subscription_naming_no_person(
    session: AsyncSession, role_session, acting_user
):
    from app.db.install_standing_test import _install

    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )
    row = await _install_subscribes(role_session, install)
    assert row.app_install_id == install.app.id
    assert row.created_by is None
    assert row.initiative_id is None


async def test_a_narrowed_install_cannot_write_a_community_subscription(
    session: AsyncSession, role_session, acting_user
):
    """The same rule the service states, held by the table's own policy."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db.install_standing_test import _install, _route

    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    s, _ = await _route(
        role_session, install, ["documents:read"], initiative_id=install.a.id
    )
    insert = text(
        "INSERT INTO webhook_subscriptions (initiative_id, app_install_id,"
        " target_url, hmac_secret, event_types, created_at, updated_at)"
        " VALUES (:i, :a, 'https://app.example.test/hook', 's3cret',"
        " ARRAY['documents.created'], now(), now())"
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.exec(insert.bindparams(i=None, a=install.app.id))
    await s.rollback()

    s, _ = await _route(
        role_session, install, ["documents:read"], initiative_id=install.a.id
    )
    await s.exec(insert.bindparams(i=install.a.id, a=install.app.id))
    await s.rollback()


async def _grant_scopes(role_session, install, scopes: list[str]) -> None:
    """Change the install's grant the way a community does: by its seat."""
    from app.models.tenant.guild_app import GuildApp
    from app.testing import route_as

    s = await role_session("app_user")
    await route_as(s, user_id=install.seat.user.id, guild_id=install.guild.id)
    row = (await s.exec(select(GuildApp).where(GuildApp.id == install.app.id))).one()
    row.granted_scopes = scopes
    s.add(row)
    await s.commit()


async def _withdraw(session, role_session, install, what: str) -> None:
    """Take one part of the install's reach away."""
    from sqlalchemy import delete

    from app.models.platform.app_service_registration import AppServiceRegistration
    from app.models.tenant.app_placement import AppPlacement
    from app.models.tenant.guild_app import GuildApp
    from app.services.marketplace.registration_lookup import invalidate_registrations

    session.expunge_all()
    if what == "placement":
        await route_session_to_guild(session, install.guild.id)
        await session.exec(
            delete(AppPlacement).where(AppPlacement.install_id == install.app.id)
        )
        await session.commit()
    elif what == "scope":
        await _grant_scopes(role_session, install, ["comments:read"])
    elif what == "install":
        await route_session_to_guild(session, install.guild.id)
        app = await session.get(GuildApp, install.app.id)
        app.enabled = False
        session.add(app)
        await session.commit()
    elif what == "registration":
        registration = (
            await session.exec(
                select(AppServiceRegistration).where(
                    AppServiceRegistration.listing_uid == install.app.listing_uid
                )
            )
        ).one()
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()
    else:
        raise AssertionError(what)
    session.expunge_all()


async def test_an_install_hears_what_it_writes_and_is_named_for_it(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """An install's subscription carries the documents of the initiative it
    is placed in, and names the app when the app wrote the change."""
    from app.db.install_standing_test import CLIENT, _install, _route
    from app.models.tenant.document import Document, DocumentType
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_document

    install = await _install(
        session, acting_user, role_session, granted=["documents:write"], placed="a"
    )
    await _install_subscribes(role_session, install)
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    in_a = await create_document(session, install.a, install.seat.user)
    session.expunge_all()
    await create_document(session, install.b, install.seat.user)
    session.expunge_all()

    s, _ = await _route(role_session, install, ["documents:write"])
    made = Document(
        initiative_id=install.a.id, name="By the app", document_type=DocumentType.native
    )
    s.add(made)
    await s.commit()
    made_id = made.id

    await poller._drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))

    changes = {
        change["resource"]["id"]: envelope
        for envelope in sent
        for change in envelope["changes"]
    }
    # B is not a placed initiative, so its document is not heard.
    assert set(changes) == {in_a.id, made_id}
    assert changes[made_id]["actor_app"] == CLIENT
    assert changes[made_id]["actor_ref"] is None
    assert changes[in_a.id]["actor_app"] is None


@pytest.mark.parametrize("what", ["placement", "scope", "install", "registration"])
async def test_an_install_hears_nothing_once_its_reach_is_withdrawn(
    session: AsyncSession, role_session, acting_user, monkeypatch, what
):
    from app.db.install_standing_test import _install
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_document

    install = await _install(
        session, acting_user, role_session, granted=["documents:read"], placed="a"
    )
    await _install_subscribes(role_session, install, initiative_id=install.a.id)
    sent = _collector(monkeypatch, poller)
    system = await role_session("app_admin")

    session.expunge_all()
    before = await create_document(session, install.a, install.seat.user)
    session.expunge_all()
    await poller._drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))
    assert [c["resource"]["id"] for e in sent for c in e["changes"]] == [before.id]

    await _withdraw(session, role_session, install, what)
    await create_document(session, install.a, install.seat.user)
    session.expunge_all()
    system.expunge_all()
    await poller._drain_guild(system, install.guild.id, now=datetime.now(timezone.utc))
    assert [c["resource"]["id"] for e in sent for c in e["changes"]] == [before.id]
