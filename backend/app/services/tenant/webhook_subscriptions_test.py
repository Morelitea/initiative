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
