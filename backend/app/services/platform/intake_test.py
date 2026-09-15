"""The intake writer: routing, binding authority, and one case per incident."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core.intake import CaseField, IntakeStream
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.models.tenant.property import PropertyDefinition
from app.services.platform import intake as intake_service
from app.services.platform.intake import CaseRefs
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)

pytestmark = pytest.mark.integration


async def _point_platform_at(session, guild_id: int | None) -> None:
    """Set (or clear) ``app_settings.operations_guild_id``."""
    await set_rls_context(session)
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()


async def _bind(session, *, guild, project, stream, **overrides):
    await set_rls_context(session, guild_id=guild.id, guild_role="admin")
    binding = IntakeBinding(stream=stream, project_id=project.id, **overrides)
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    return binding


@pytest.fixture
async def bound(session):
    """A deployment pointed at a guild with the support stream bound."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    await _point_platform_at(session, guild.id)
    binding = await _bind(
        session,
        guild=guild,
        project=project,
        stream=IntakeStream.support.value,
    )
    return {
        "user": user,
        "guild": guild,
        "initiative": initiative,
        "project": project,
        "binding": binding,
    }


async def test_unbound_deployment_files_nothing(session):
    """Every install starts here: no pointer, so the writer is a no-op."""
    await _point_platform_at(session, None)
    outcome = await intake_service.open_case(
        IntakeStream.support, title="Cannot sign in"
    )
    assert outcome is None


async def test_pointer_without_a_binding_files_nothing(session):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await _point_platform_at(session, guild.id)

    outcome = await intake_service.open_case(
        IntakeStream.support, title="Cannot sign in"
    )
    assert outcome is None


async def test_a_bound_stream_lands_a_task_in_its_project(session, bound):
    outcome = await intake_service.open_case(
        IntakeStream.support, title="Cannot sign in", body="It says my code expired."
    )
    assert outcome is not None
    assert outcome.opened is True

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.project_id == bound["project"].id
    assert task.title == "Cannot sign in"
    assert task.description == "It says my code expired."


async def test_a_system_opened_case_names_no_author(session, bound):
    """Nobody signed in created it, and ``created_by`` says so."""
    outcome = await intake_service.open_case(IntakeStream.support, title="Help")
    assert outcome is not None

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.created_by is None


async def test_a_disabled_binding_receives_nothing(session, bound):
    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    binding = (
        await session.exec(
            select(IntakeBinding).where(IntakeBinding.id == bound["binding"].id)
        )
    ).one()
    binding.enabled = False
    session.add(binding)
    await session.commit()

    assert await intake_service.open_case(IntakeStream.support, title="Help") is None


async def test_refs_land_as_property_values(session, bound):
    outcome = await intake_service.open_case(
        IntakeStream.support,
        title="Help",
        refs=CaseRefs(subject_user=4242, subject_guild=7),
    )
    assert outcome is not None

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    definitions = {
        definition.name: definition
        for definition in await session.exec(
            select(PropertyDefinition).where(
                PropertyDefinition.initiative_id == bound["initiative"].id
            )
        )
    }
    assert CaseField.subject_user.value in definitions
    assert CaseField.subject_guild.value in definitions


async def test_a_sustained_run_makes_one_case(session, bound):
    """Two crossings inside the window are one case, not two."""
    first = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    second = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    assert first is not None and second is not None
    assert second.task_id == first.task_id
    assert second.opened is False


async def test_a_crossing_past_the_window_moves_the_mark(session, bound):
    start = datetime.now(timezone.utc)
    first = await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        dedupe_key="refused:42",
        now=start,
    )
    assert first is not None

    later = start + timedelta(hours=2)
    again = await intake_service.open_case(
        IntakeStream.support,
        title="Refused sign-ins",
        dedupe_key="refused:42",
        now=later,
    )
    assert again is not None
    assert again.task_id == first.task_id
    assert again.opened is False

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    case = (
        await session.exec(
            select(IntakeCase).where(IntakeCase.task_id == first.task_id)
        )
    ).one()
    assert case.last_seen_at == later


async def test_a_closed_case_opens_a_new_one(session, bound):
    first = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    assert first is not None

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    task = (await session.exec(select(Task).where(Task.id == first.task_id))).one()
    done = (
        await session.exec(
            select(TaskStatus)
            .where(TaskStatus.project_id == bound["project"].id)
            .where(TaskStatus.category == TaskStatusCategory.done)
        )
    ).first()
    assert done is not None
    task.task_status_id = done.id
    session.add(task)
    await session.commit()

    second = await intake_service.open_case(
        IntakeStream.support, title="Refused sign-ins", dedupe_key="refused:42"
    )
    assert second is not None
    assert second.opened is True
    assert second.task_id != first.task_id


async def test_a_key_longer_than_its_column_is_refused(session, bound):
    with pytest.raises(ValueError):
        await intake_service.open_case(
            IntakeStream.support, title="x", dedupe_key="k" * 500
        )
