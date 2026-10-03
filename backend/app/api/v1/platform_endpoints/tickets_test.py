"""Filing a ticket: who may ask for help, where it lands, what each stream
offers, and what happens when nobody is set up to receive it.

Reports are filed through the same route; what becomes of them is
``tenant_endpoints/moderation_test.py``'s."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.intake import IntakeStream, meta
from app.core.messages import SupportMessages, TicketMessages
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import CommunityRole
from app.models.platform.guild_administration import GuildAdministration
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)
from app.db.request_context import SystemGuild, Unattributed


TICKETS = "/api/v1/me/tickets"


async def _ask(client, actor, guild_id, **body):
    payload = {
        "stream": "support",
        "community_id": guild_id,
        "subject": "Cannot open a project",
        "body": "It spins forever.",
    }
    payload.update(body)
    return await client.post(TICKETS, json=payload, headers=actor.headers)


async def _offered(client, actor, guild_id=None) -> dict:
    """What every stream offers ``actor``, standing in ``guild_id``."""
    params = {} if guild_id is None else {"community_id": guild_id}
    response = await client.get(
        f"{TICKETS}/availability", params=params, headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _set_contacts(session, *, general=None, **streams) -> None:
    """Who to contact, the way the Intake page's contacts card writes it."""
    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.intake_general_contact = general
    row.intake_contacts = streams
    session.add(row)
    await session.commit()


async def _set_support(session, guild_id: int, enabled: bool) -> None:
    """Grant the entitlement, the way the operator's Guilds tab does."""
    await set_rls_context(session, Unattributed())
    row = (
        await session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
        )
    ).one()
    row.support_enabled = enabled
    session.add(row)
    await session.commit()


@pytest.fixture
async def operations(session):
    """A deployment with somewhere for support cases to go."""
    staff = await create_user(session)
    ops_guild = await create_guild(session, creator=staff)
    ops_initiative = await create_initiative(session, ops_guild, staff)
    ops_project = await create_project(session, ops_initiative, staff)

    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = ops_guild.id
    session.add(row)
    await session.commit()

    await set_rls_context(session, SystemGuild(ops_guild.id))
    session.add(IntakeBinding(stream=IntakeStream.support, project_id=ops_project.id))
    await session.commit()
    await set_rls_context(session, Unattributed())
    return {"guild": ops_guild, "project": ops_project}


async def test_support_is_off_until_the_operator_turns_it_on(client, acting_user):
    """The default, and not a community admin's to change: the deployment that
    would receive the requests decides it is staffing them."""
    member = await acting_user(guild_role=CommunityRole.member)
    response = await _ask(client, member, member.guild.id)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == SupportMessages.NOT_AVAILABLE


async def test_a_member_can_ask_for_help(client, session, acting_user, operations):
    """Every member, not only an admin: the person who needs help is rarely
    the person who administers anything."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)

    response = await _ask(
        client, member, member.guild.id, subject="Cannot sign in on my phone"
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    assert case.stream == IntakeStream.support.value
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert task.title == "Cannot sign in on my phone"
    assert task.project_id == operations["project"].id


async def test_the_case_names_who_asked_and_where_from(
    client, session, acting_user, operations
):
    """So whoever picks it up can reach them without the endpoint resolving
    anybody."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    assert (await _ask(client, member, member.guild.id)).status_code == 202

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    from app.models.tenant.property import PropertyValue

    values = (
        await session.exec(
            select(PropertyValue).where(
                PropertyValue.entity_type == "task",
                PropertyValue.entity_id == case.task_id,
            )
        )
    ).all()
    held = {int(v.value_number) for v in values if v.value_number is not None}
    assert member.user.id in held
    assert member.guild.id in held


async def test_asking_where_nothing_is_bound_says_so(client, session, acting_user):
    """Support is on, but the deployment routes nothing. The asker is told,
    rather than being thanked for a request that reached nobody."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)

    response = await _ask(client, member, member.guild.id)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == SupportMessages.NOWHERE_TO_SEND


async def test_a_stranger_cannot_ask_on_a_community_they_are_not_in(
    client, session, acting_user, operations
):
    """The guild gate, which is not this endpoint's to re-decide."""
    host = await acting_user(guild_role=CommunityRole.admin)
    await _set_support(session, host.guild.id, True)
    outsider = await acting_user(guild_role=CommunityRole.member)

    response = await _ask(client, outsider, host.guild.id)
    assert response.status_code == 403, response.text


@pytest.mark.always
async def test_every_support_error_code_is_localized():
    """A refusal reaches the reader as its own sentence."""
    import json
    from pathlib import Path

    codes = {
        value
        for name, value in vars(SupportMessages).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    locales = Path(__file__).resolve().parents[4].parent / "frontend/public/locales"
    for locale in ("de", "en", "es", "fr"):
        catalogue = json.loads((locales / locale / "errors.json").read_text())
        missing = sorted(codes - set(catalogue))
        assert not missing, f"{locale}/errors.json is missing {missing}"


async def test_the_help_form_is_offered_once_both_halves_are_there(
    client, session, acting_user, operations
):
    """The sidebar draws the control either way, so this answers what it does.

    Both halves have to hold: a form that can only answer "nowhere to send it"
    is worse than the address it would have replaced.
    """
    member = await acting_user(guild_role=CommunityRole.member)

    assert (await _offered(client, member, member.guild.id))["support"][
        "mode"
    ] == "none"
    await _set_support(session, member.guild.id, True)
    assert (await _offered(client, member, member.guild.id))["support"][
        "mode"
    ] == "form"


async def test_no_form_is_offered_where_nothing_is_bound(client, session, acting_user):
    """Entitled, but the deployment routes nothing — so no form that would
    503, and with no address set, nothing at all."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)

    offered = await _offered(client, member, member.guild.id)
    assert offered["support"] == {"mode": "none", "contact": None}


async def test_without_a_form_the_streams_address_is_offered(
    client, session, acting_user
):
    """Where nothing is set up to receive a stream, its address is the way to
    reach the people who run the deployment — the stream's own, else the
    general one, never another stream's."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_contacts(
        session, general="ops@example.org", security="security@example.org"
    )

    offered = await _offered(client, member, member.guild.id)
    assert offered["security"] == {"mode": "email", "contact": "security@example.org"}
    assert offered["support"] == {"mode": "email", "contact": "ops@example.org"}
    assert offered["feedback"] == {"mode": "email", "contact": "ops@example.org"}


async def test_a_report_is_always_a_form(client, session, acting_user):
    """A community's own content goes to its own moderators and needs no
    platform, so the report form is there whatever the deployment set up —
    with the address beside it for a report the platform would have to take."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_contacts(session, moderation="trust@example.org")

    offered = await _offered(client, member)
    assert offered["moderation"] == {"mode": "form", "contact": "trust@example.org"}


async def test_help_is_offered_only_from_a_community_the_reader_is_in(
    client, session, acting_user, operations
):
    """Whether somebody may ask from a community is asked as them."""
    host = await acting_user(guild_role=CommunityRole.admin)
    await _set_support(session, host.guild.id, True)
    outsider = await acting_user(guild_role=CommunityRole.member)

    offered = await _offered(client, outsider, host.guild.id)
    assert offered["support"]["mode"] == "none"


async def test_a_blank_request_is_refused(client, session, acting_user, operations):
    """Whitespace is characters, so the length bound alone admits a case whose
    title and description are blank on the board somebody works from."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)

    response = await _ask(client, member, member.guild.id, subject="   ", body="\t\n ")
    assert response.status_code == 422, response.text


async def test_what_is_stored_is_what_was_meant(
    client, session, acting_user, operations
):
    """Trimmed on the way in, so the queue reads the words and not the padding."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    assert (
        await _ask(client, member, member.guild.id, subject="  Padded  ")
    ).status_code == 202

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert task.title == "Padded"


async def test_one_account_can_only_file_so_often(
    client, session, acting_user, operations, monkeypatch
):
    """Every filing is a case somebody works by hand, so one account's run of
    them is held to the stream's declared pace."""
    from dataclasses import replace

    from app.core import intake
    from app.core.rate_limit import limiter

    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    monkeypatch.setitem(
        intake.STREAMS,
        IntakeStream.support,
        replace(
            intake.STREAMS[IntakeStream.support],
            filing_rate="2/hour",
            max_open_per_filer=None,
        ),
    )
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    try:
        for _ in range(2):
            assert (await _ask(client, member, member.guild.id)).status_code == 202
        refused = await _ask(client, member, member.guild.id)
    finally:
        limiter.reset()

    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"] == TicketMessages.FILING_TOO_FAST


async def test_one_account_holds_only_so_many_open_cases(
    client, session, acting_user, operations
):
    """The cap is read from the cases themselves, so closing one makes room at
    once."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    cap = meta(IntakeStream.support).max_open_per_filer
    assert cap is not None

    for _ in range(cap):
        assert (await _ask(client, member, member.guild.id)).status_code == 202
    refused = await _ask(client, member, member.guild.id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == TicketMessages.TOO_MANY_OPEN

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    done = (
        await session.exec(
            select(TaskStatus).where(
                TaskStatus.project_id == operations["project"].id,
                TaskStatus.category == TaskStatusCategory.done,
            )
        )
    ).first()
    task = (await session.exec(select(Task).limit(1))).one()
    task.task_status_id = done.id
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())

    assert (await _ask(client, member, member.guild.id)).status_code == 202


async def test_the_case_is_connected_to_who_asked_and_opens_with_their_words(
    client, session, acting_user, operations
):
    """The asker is recorded as the case's filer, with their subject, and what
    they wrote opens the case under their name, said to them — the start of
    the conversation with them rather than a description somebody rewrites."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    response = await _ask(
        client, member, member.guild.id, subject="Lost my phone", body="Help."
    )
    assert response.status_code == 202, response.text

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    case = (await session.exec(select(IntakeCase))).one()
    assert case.filer_user_id == member.user.id
    assert case.filer_subject == "Lost my phone"
    (opening,) = (
        await session.exec(select(Comment).where(Comment.task_id == case.task_id))
    ).all()
    assert opening.content == "Help."
    assert opening.created_by == member.user.id
    assert opening.audience == CommentAudience.filer
    assert opening.system_kind is None


@pytest.mark.always
async def test_every_ticket_error_code_is_localized():
    """A refusal reaches the reader as its own sentence."""
    import json
    from pathlib import Path

    codes = {
        value
        for name, value in vars(TicketMessages).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    locales = Path(__file__).resolve().parents[4].parent / "frontend/public/locales"
    for locale in ("de", "en", "es", "fr"):
        catalogue = json.loads((locales / locale / "errors.json").read_text())
        missing = sorted(codes - set(catalogue))
        assert not missing, f"{locale}/errors.json is missing {missing}"
