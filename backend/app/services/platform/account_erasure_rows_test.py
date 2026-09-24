"""What erasing an account does to every guild-schema row that named that person.

Fourteen of those columns used to declare a delete rule — nine ``ON DELETE
CASCADE``, five ``ON DELETE SET NULL`` — on a key no guild schema has ever
held. Provisioning copies intra-schema keys only, and ``20260922_0349`` dropped
the ones ``guild_template`` alone still carried, so the rules described a
Postgres that would clear the column or take the row, and no Postgres ever did.
``app.models.tenant.cross_schema_refs_test`` now holds the line at declaring
one; this is the other half, and the half that is load-bearing: an account with
a row in each of those twelve tables, erased, and an assertion per table about
what is actually left.

Three outcomes appear below, and the distinction is the point:

* **The row goes** — per-person state and anything held in custody for them.
  ``app.services.platform.users`` deletes it, in every guild schema.
* **The row stays, un-attributed** — a record of something that happened,
  whose subject can be dropped without losing the event.
* **The row stays, still naming them** — authorship. ``created_by`` is a weak
  reference on purpose: it outlives the account so an old thread keeps telling
  one departed author from another, rather than merging them into a shared
  placeholder (see ``CreatedByMixin``). A block tombstone stays for a
  neighbouring reason — it outlives the membership it was placed on.

``webhook_subscriptions.created_by`` used to be none of those — it named the
account a delivery was read as. It is ordinary authorship since
``history/webhook-scope-not-principal-design.md``, so it belongs to the third
group with the rest.

The two erasure paths are both exercised, because they do not do the same
things: ``soft_delete_user`` is what the product runs (the deletion request and
the retention purge; the row stays, emptied), and ``hard_delete_user`` is the
operator's removal of the row itself.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.ai_member_key import GuildAIMemberKey
from app.models.tenant.ai_member_pref import GuildAIMemberPref
from app.models.tenant.comment import Comment
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.models.tenant.guild_app_user_delegation import GuildAppUserDelegation
from app.models.tenant.initiative import InitiativeJoinRequest
from app.models.tenant.reaction import Reaction
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.platform import users as user_service
from app.testing.factories import (
    create_calendar,
    create_calendar_event,
    create_comment,
    create_document,
    create_guild,
    create_guild_app,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_reaction,
    create_task,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild

pytestmark = [pytest.mark.integration, pytest.mark.service]


def _service_definition() -> dict:
    """A service app declaring one connection, so a credential row has a home."""
    return {
        "app_kind": "service",
        "service": {"public_id": "tests.erasure", "protocol": 1},
        "features": [],
        "default_name": "Erasure",
        "connections": [
            {
                "id": "admin",
                "scope": "static",
                "label": {"en": "Admin API"},
                "fields": [{"key": "token", "type": "string", "label": {"en": "T"}}],
            }
        ],
    }


async def _seed(session: AsyncSession) -> SimpleNamespace:
    """One member, and one row naming them in each of the twelve tables."""
    keeper = await create_user(session, email=f"keeper-{secrets.token_hex(4)}@e.test")
    victim = await create_user(session, email=f"leaver-{secrets.token_hex(4)}@e.test")
    guild = await create_guild(session, creator=keeper)
    await create_guild_membership(
        session, user=victim, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, keeper)
    await create_initiative_member(session, initiative=initiative, user=victim)
    project = await create_project(session, initiative, keeper)
    task = await create_task(session, project)
    document = await create_document(session, initiative, keeper)
    calendar = await create_calendar(session, initiative, keeper)
    event = await create_calendar_event(session, calendar, keeper)
    app = await create_guild_app(
        session, guild, keeper, definition=_service_definition()
    )

    # Authorship: a comment they wrote, and an emoji they put on it.
    comment = await create_comment(session, victim, document=document)
    reaction = await create_reaction(session, victim, comment=comment)

    now = datetime.now(timezone.utc)
    await route_session_to_guild(session, guild.id)
    rows = {
        # Held in custody for them: an API key and the preference beside it.
        "ai_key": GuildAIMemberKey(
            user_id=victim.id,
            connection_scope="guild",
            connection_id=1,
            api_key_encrypted="ciphertext",
        ),
        "ai_pref": GuildAIMemberPref(
            user_id=victim.id, connection_scope="guild", connection_id=1, enabled=True
        ),
        # A receipt that a reminder for this event reached this person.
        "dispatch": EventReminderDispatch(
            event_id=event.id,
            user_id=victim.id,
            event_start_at=now,
            sent_at=now,
        ),
        # A vendor credential they connected, and one they blocked for somebody.
        "connection": GuildAppUserConnection(
            app_id=app.id,
            connection_id="admin",
            user_id=victim.id,
            connection_ref=secrets.token_hex(8),
        ),
        "blocked_connection": GuildAppUserConnection(
            app_id=app.id,
            connection_id="admin",
            user_id=keeper.id,
            connection_ref=secrets.token_hex(8),
            blocked_at=now,
            blocked_by_id=victim.id,
        ),
        # An authorization for an app to act as them, and one they withdrew.
        "delegation": GuildAppUserDelegation(
            app_id=app.id, user_id=victim.id, can_read=True
        ),
        "revoked_delegation": GuildAppUserDelegation(
            app_id=app.id,
            user_id=keeper.id,
            can_read=True,
            revoked_at=now,
            revoked_by_id=victim.id,
        ),
        # A request they made, and one they ruled on.
        "own_request": InitiativeJoinRequest(
            initiative_id=initiative.id,
            user_id=victim.id,
            status="approved",
            resolved_at=now,
            resolved_by=keeper.id,
        ),
        "ruled_request": InitiativeJoinRequest(
            initiative_id=initiative.id,
            user_id=keeper.id,
            status="denied",
            resolved_at=now,
            resolved_by=victim.id,
        ),
        # Queued notifications naming them as the one who acted.
        "reaction_digest": ReactionDigestItem(
            user_id=keeper.id,
            reaction_id=reaction.id,
            target_type="comment",
            target_id=comment.id,
            emoji="\N{THUMBS UP SIGN}",
            target_path="/x",
            context_title="a comment",
            reactor_name="Leaver",
            reactor_id=victim.id,
        ),
        "assignment_digest": TaskAssignmentDigestItem(
            user_id=keeper.id,
            task_id=task.id,
            project_id=project.id,
            task_title="A task",
            project_name="A project",
            assigned_by_name="Leaver",
            assigned_by_id=victim.id,
        ),
        # A live outbound integration they registered.
        "webhook": WebhookSubscription(
            initiative_id=initiative.id,
            created_by=victim.id,
            target_url="https://example.test/hook",
            hmac_secret=secrets.token_hex(16),
            event_types=["task.created"],
            created_at=now,
            updated_at=now,
        ),
    }
    for row in rows.values():
        session.add(row)
    await session.commit()
    for row in rows.values():
        await session.refresh(row)

    seeded = SimpleNamespace(
        guild_id=guild.id,
        victim_id=victim.id,
        keeper_id=keeper.id,
        comment_id=comment.id,
        reaction_id=reaction.id,
        **{name: row.id for name, row in rows.items()},
    )
    session.expunge_all()
    return seeded


async def _reread(session: AsyncSession, guild_id: int, model, row_id: int):
    """One row from the guild's schema, or ``None`` if erasure took it."""
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    return (await session.exec(select(model).where(model.id == row_id))).one_or_none()


# --- the row goes ------------------------------------------------------------


async def test_the_key_held_for_them_goes(session: AsyncSession, role_session):
    """An encrypted API key is held in custody, so erasure must not leave it."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    assert await _reread(session, s.guild_id, GuildAIMemberKey, s.ai_key) is None


async def test_the_preference_beside_it_goes(session: AsyncSession, role_session):
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    assert await _reread(session, s.guild_id, GuildAIMemberPref, s.ai_pref) is None


async def test_their_grants_go(session: AsyncSession, role_session):
    """Every per-person DAC grant in the schema, in one delete."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    session.expunge_all()
    await route_session_to_guild(session, s.guild_id)
    remaining = (
        await session.exec(
            select(ResourceGrant).where(ResourceGrant.user_id == s.victim_id)
        )
    ).all()
    assert remaining == []


# --- the row stays, un-attributed -------------------------------------------


async def test_the_reaction_digest_forgets_who_reacted(
    session: AsyncSession, role_session
):
    """Somebody else's queued line survives; the id behind ``reactor_name``
    does not. The pair matches what the assignment digest already gets."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    row = await _reread(session, s.guild_id, ReactionDigestItem, s.reaction_digest)
    assert row is not None
    assert row.reactor_id is None


async def test_the_assignment_digest_forgets_who_assigned(
    session: AsyncSession, role_session
):
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    row = await _reread(
        session, s.guild_id, TaskAssignmentDigestItem, s.assignment_digest
    )
    assert row is not None
    assert row.assigned_by_id is None


# --- the row stays, still naming them ----------------------------------------


async def test_their_comment_keeps_its_author(session: AsyncSession, role_session):
    """Authorship is a weak reference: the thread still tells them apart."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    comment = await _reread(session, s.guild_id, Comment, s.comment_id)
    assert comment is not None
    assert comment.created_by == s.victim_id


async def test_their_reaction_keeps_its_author(session: AsyncSession, role_session):
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    reaction = await _reread(session, s.guild_id, Reaction, s.reaction_id)
    assert reaction is not None
    assert reaction.created_by == s.victim_id


async def test_a_block_they_placed_outlives_them(session: AsyncSession, role_session):
    """A block outlives the membership it was placed on, and the account too."""
    s = await _seed(session)
    await user_service.soft_delete_user(await role_session("app_admin"), s.victim_id)
    row = await _reread(
        session, s.guild_id, GuildAppUserConnection, s.blocked_connection
    )
    assert row is not None
    assert row.blocked_by_id == s.victim_id


# --- the erasure path ends what the account opened ---------------------------


async def test_erasure_ends_the_credentials_they_connected(
    session: AsyncSession, role_session
):
    """Losing the account has to end the vendor access it opened."""
    s = await _seed(session)
    await user_service.soft_delete_user(await role_session("app_admin"), s.victim_id)
    assert (
        await _reread(session, s.guild_id, GuildAppUserConnection, s.connection) is None
    )


async def test_erasure_ends_what_an_app_could_do_as_them(
    session: AsyncSession, role_session
):
    s = await _seed(session)
    await user_service.soft_delete_user(await role_session("app_admin"), s.victim_id)
    assert (
        await _reread(session, s.guild_id, GuildAppUserDelegation, s.delegation) is None
    )


async def test_the_reminder_ledger_forgets_them(session: AsyncSession, role_session):
    """One row per (event, person), kept only to not send the same reminder
    twice. It can never match again, and it names somebody who is gone."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    assert await _reread(session, s.guild_id, EventReminderDispatch, s.dispatch) is None


# --- the row stays, still naming them ----------------------------------------


async def test_a_delegation_they_revoked_keeps_naming_them(
    session: AsyncSession, role_session
):
    """Their own grants go; a withdrawal they performed on somebody else's is a
    record of something they did, and reads like the block above."""
    s = await _seed(session)
    await user_service.soft_delete_user(await role_session("app_admin"), s.victim_id)
    row = await _reread(
        session, s.guild_id, GuildAppUserDelegation, s.revoked_delegation
    )
    assert row is not None
    assert row.revoked_by_id == s.victim_id


async def test_the_join_requests_stay_on_both_sides(
    session: AsyncSession, role_session
):
    """A request carries a message its author wrote, and a ruling names the
    manager who made it. Erasure keeps both, the way it keeps a comment."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    made = await _reread(session, s.guild_id, InitiativeJoinRequest, s.own_request)
    assert made is not None
    assert made.user_id == s.victim_id
    ruled = await _reread(session, s.guild_id, InitiativeJoinRequest, s.ruled_request)
    assert ruled is not None
    assert ruled.resolved_by == s.victim_id


async def test_the_webhook_they_registered_stays(session: AsyncSession, role_session):
    """A subscription is the community's integration configuration, and its
    reach is the scope it names rather than anyone's standing — so erasing the
    person who registered it is not a decision about it. ``created_by`` records
    who that was, like any other author column."""
    s = await _seed(session)
    await user_service.hard_delete_user(await role_session("app_admin"), s.victim_id)
    row = await _reread(session, s.guild_id, WebhookSubscription, s.webhook)
    assert row is not None
    assert row.active is True
    assert row.created_by == s.victim_id
