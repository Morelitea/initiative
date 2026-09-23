"""What becomes of a subscription when the account behind it stops standing.

A subscription delivers what its creator can reach and nothing more: the poller
looks the owner up, establishes their standing the way a request of theirs
would, and reads the change log as them (``outbox_poller._drain_subscription``).
So ``created_by`` here is not authorship the way it is on a comment — it is the
authorization the whole feature rests on, re-derived every pass.

That gate already holds: the tests below start by proving delivery stops on its
own once the owner is gone. What it cannot do is *say* so. The poller stands
down before it attempts a delivery, so ``dead_letter_count`` — the one signal a
subscription has for "this is not working" — never moves, and there is no other
surface; a row left ``active`` reads exactly like a working one.

So the row is settled where the standing ends, the way ``deactivate_for_install``
already settles one whose app was uninstalled:

* **The owner leaves the community** — deactivated. They may come back, and
  ``active`` is reversible.
* **The account is erased** — deleted. It cannot come back, and what a
  standing-down row would keep is a target URL and the secret its receiver
  signs deliveries with.
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


async def _subscribe(session: AsyncSession, *, guild_id: int, user_id: int) -> None:
    """One guild-wide subscription on every task creation, written directly."""
    await route_session_to_guild(session, guild_id)
    now = datetime.now(timezone.utc)
    row = WebhookSubscription(
        initiative_id=None,
        created_by=user_id,
        target_url="https://example.test/hook",
        hmac_secret="secret",
        event_types=["tasks.created"],
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()


async def _rows(session: AsyncSession, guild_id: int) -> list[WebhookSubscription]:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    return list(await session.exec(select(WebhookSubscription)))


async def test_delivery_stops_once_the_owner_row_is_gone(
    session: AsyncSession, role_session, acting_user, monkeypatch
):
    """The gate this all rests on, asserted directly: with no owner to
    establish standing for, a pass delivers nothing — including events written
    while the account still existed."""
    from app.services.platform import users as user_service
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id, user_id, project = a.guild.id, a.user.id, a.project
    await create_task(session, project)
    await _subscribe(session, guild_id=guild_id, user_id=user_id)

    sent: list[dict] = []

    async def _accept(*, target_url, secret, envelope):
        sent.append(envelope)
        return True

    monkeypatch.setattr(poller, "deliver", _accept)
    system = await role_session("app_admin")

    await poller._drain_guild(system, guild_id, now=datetime.now(timezone.utc))
    assert sent, "nothing was delivered even with the owner in place"
    delivered = len(sent)

    session.expunge_all()
    await create_task(session, project)
    session.expunge_all()
    await user_service.hard_delete_user(system, user_id)
    session.expunge_all()

    await poller._drain_guild(system, guild_id, now=datetime.now(timezone.utc))
    assert len(sent) == delivered, (
        f"{len(sent) - delivered} batches were delivered for an account that "
        "no longer exists"
    )


async def test_erasing_the_account_takes_the_subscription(
    session: AsyncSession, role_session, acting_user
):
    from app.services.platform import users as user_service

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    guild_id, user_id = a.guild.id, a.user.id
    await _subscribe(session, guild_id=guild_id, user_id=user_id)

    await user_service.hard_delete_user(await role_session("app_admin"), user_id)

    assert await _rows(session, guild_id) == []


async def test_anonymizing_the_account_takes_it_too(
    session: AsyncSession, role_session, acting_user
):
    """The path the product actually runs — a deletion request, and the
    retention purge behind it — keeps the account row and must still take this."""
    from app.services.platform import users as user_service

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    guild_id, user_id = a.guild.id, a.user.id
    await _subscribe(session, guild_id=guild_id, user_id=user_id)

    await user_service.soft_delete_user(await role_session("app_admin"), user_id)

    assert await _rows(session, guild_id) == []


async def test_leaving_the_community_stands_the_subscription_down(
    session: AsyncSession, role_session, acting_user
):
    """Deactivated, not deleted: they may come back, and until then the list
    should not report a subscription that can deliver nothing as live."""
    from app.services.platform import guilds as guilds_service

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    guild_id, user_id = a.guild.id, a.user.id
    await _subscribe(session, guild_id=guild_id, user_id=user_id)

    system = await role_session("app_admin")
    session.expunge_all()
    from app.db.session import set_rls_context

    await set_rls_context(system, guild_id=guild_id)
    await guilds_service.remove_user_from_guild(
        system, guild_id=guild_id, user_id=user_id
    )
    await system.commit()

    rows = await _rows(session, guild_id)
    assert len(rows) == 1
    assert rows[0].active is False
    assert rows[0].created_by == user_id


async def test_a_subscription_in_another_community_is_untouched(
    session: AsyncSession, role_session, acting_user
):
    """Leaving one community ends nothing in another — that relationship has
    not ended."""
    from app.services.platform import guilds as guilds_service
    from app.db.session import set_rls_context

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    b = await acting_user(guild_role=GuildRole.admin, initiative=True)
    # The same person, admin of a second community.
    from app.testing.factories import create_guild_membership

    await create_guild_membership(
        session, user=a.user, guild=b.guild, role=GuildRole.admin
    )
    await _subscribe(session, guild_id=a.guild.id, user_id=a.user.id)
    await _subscribe(session, guild_id=b.guild.id, user_id=a.user.id)

    system = await role_session("app_admin")
    session.expunge_all()
    await set_rls_context(system, guild_id=a.guild.id)
    await guilds_service.remove_user_from_guild(
        system, guild_id=a.guild.id, user_id=a.user.id
    )
    await system.commit()

    left = await _rows(session, a.guild.id)
    kept = await _rows(session, b.guild.id)
    assert [row.active for row in left] == [False]
    assert [row.active for row in kept] == [True]
