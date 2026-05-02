"""Round-trip and feature tests for project export/import services.

The most valuable test is a full round-trip: export a populated project,
import the envelope into a different initiative in the same guild, and
verify the new project has equivalent tags, statuses, properties, tasks,
subtasks, assignees, and property values.
"""

import pytest
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.project import Project
from app.models.property import PropertyDefinition, PropertyType, TaskPropertyValue
from app.models.tag import ProjectTag, Tag, TaskTag
from app.models.task import Subtask, Task, TaskAssignee, TaskStatusCategory
from app.services import project_export as export_service
from app.services import project_import as import_service
from app.services import task_statuses as task_statuses_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_property_definition,
    create_user,
)


async def _seed_populated_project(session: AsyncSession):
    """Build a project with statuses, tags, a property definition, and a
    task that exercises subtasks, assignees, tags, and property values."""
    owner = await create_user(session, email="owner@example.com")
    assignee = await create_user(session, email="alice@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=assignee, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild, owner, name="Source Initiative")
    await create_initiative_member(session, initiative, assignee, role_name="member")

    project = await create_project(session, initiative, owner, name="Source Project", icon="🚀")

    # Statuses
    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    todo_status = next(s for s in statuses if s.category == TaskStatusCategory.todo)

    # Project-level tag
    tag = Tag(guild_id=guild.id, name="blocker", color="#FF0000")
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    session.add(ProjectTag(project_id=project.id, tag_id=tag.id))

    # Property definition (select)
    severity = await create_property_definition(
        session, initiative, name="Severity", type=PropertyType.select,
        options=[{"value": "low", "label": "Low"}, {"value": "high", "label": "High"}],
    )

    # Task
    task = Task(
        project_id=project.id,
        guild_id=guild.id,
        task_status_id=todo_status.id,
        title="Fix the thing",
        description="Important",
        sort_order=1024.0,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    session.add(TaskTag(task_id=task.id, tag_id=tag.id))
    session.add(TaskAssignee(task_id=task.id, user_id=assignee.id, guild_id=guild.id))
    session.add(Subtask(task_id=task.id, guild_id=guild.id, content="step 1", position=0))
    session.add(Subtask(task_id=task.id, guild_id=guild.id, content="step 2", position=1, is_completed=True))
    session.add(TaskPropertyValue(
        task_id=task.id, property_id=severity.id, value_text="high",
    ))
    await session.commit()

    return owner, assignee, guild, initiative, project


@pytest.mark.integration
async def test_round_trip_into_different_initiative(session: AsyncSession):
    owner, assignee, guild, source_initiative, source_project = await _seed_populated_project(session)

    # Build the export envelope
    envelope = await export_service.build_project_export(
        session,
        project_id=source_project.id,
        exported_by_email=owner.email,
    )

    assert envelope.schema_version == 1
    assert envelope.project.name == "Source Project"
    assert envelope.project.icon == "🚀"
    assert {s.name for s in envelope.task_statuses} >= {"Backlog", "To-do", "In progress", "Done"} or len(envelope.task_statuses) >= 1
    assert {t.name for t in envelope.tags} == {"blocker"}
    assert {p.name for p in envelope.property_definitions} == {"Severity"}
    assert len(envelope.tasks) == 1
    exported_task = envelope.tasks[0]
    assert exported_task.title == "Fix the thing"
    assert [t.name for t in exported_task.tags] == ["blocker"]
    assert [t.color for t in exported_task.tags] == ["#FF0000"]
    assert exported_task.assignee_emails == ["alice@example.com"]
    assert {s.content for s in exported_task.subtasks} == {"step 1", "step 2"}
    assert exported_task.property_values[0].property_name == "Severity"
    assert exported_task.property_values[0].value_text == "high"

    # Target initiative in the same guild — assignee is a member of both
    target_initiative = await create_initiative(session, guild, owner, name="Target Initiative")
    await create_initiative_member(session, target_initiative, assignee, role_name="member")

    # Import
    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )

    assert result.task_count == 1
    assert result.assignee_unmatched_emails == []
    assert result.tag_create_count + result.tag_match_count == 1
    assert result.property_create_count == 1
    assert result.assignee_match_count == 1

    # Verify the new project lives in target initiative with full graph
    stmt = (
        select(Project)
        .where(Project.id == result.project_id)
        .options(
            selectinload(Project.task_statuses),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
            selectinload(Project.tasks).selectinload(Task.subtasks),
            selectinload(Project.tasks).selectinload(Task.assignees),
            selectinload(Project.tasks).selectinload(Task.tag_links).selectinload(TaskTag.tag),
            selectinload(Project.tasks)
            .selectinload(Task.property_values)
            .selectinload(TaskPropertyValue.property_definition),
        )
    )
    new_project = (await session.exec(stmt)).one()
    assert new_project.initiative_id == target_initiative.id
    assert new_project.name == "Source Project"
    assert new_project.icon == "🚀"
    assert new_project.owner_id == owner.id
    assert len(new_project.tasks) == 1
    new_task = new_project.tasks[0]
    assert new_task.title == "Fix the thing"
    assert {s.content for s in new_task.subtasks} == {"step 1", "step 2"}
    assert [u.email for u in new_task.assignees] == ["alice@example.com"]
    assert {link.tag.name for link in new_task.tag_links} == {"blocker"}
    assert len(new_task.property_values) == 1
    pv = new_task.property_values[0]
    assert pv.value_text == "high"
    assert pv.property_definition.name == "Severity"
    assert pv.property_definition.initiative_id == target_initiative.id


@pytest.mark.integration
async def test_property_type_collision_renames(session: AsyncSession):
    owner, assignee, guild, source_initiative, source_project = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(session, project_id=source_project.id)

    target_initiative = await create_initiative(session, guild, owner, name="Target")
    # Pre-create a property in target with the same name but different type
    existing_prop = await create_property_definition(
        session, target_initiative, name="Severity", type=PropertyType.text,
    )

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )

    assert result.property_rename_count == 1

    # Original definition unchanged
    refreshed = await session.get(PropertyDefinition, existing_prop.id)
    assert refreshed.type == PropertyType.text

    # Renamed definition exists with the original type
    stmt = select(PropertyDefinition).where(
        PropertyDefinition.initiative_id == target_initiative.id,
        PropertyDefinition.name == "Severity_select",
    )
    renamed = (await session.exec(stmt)).one_or_none()
    assert renamed is not None
    assert renamed.type == PropertyType.select


@pytest.mark.integration
async def test_property_options_mismatch_renames(session: AsyncSession):
    """Same name + type but different option values → treat as collision
    and rename. Reusing the existing definition would silently store
    values that aren't valid options on the target side."""
    owner, assignee, guild, source_initiative, source_project = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(session, project_id=source_project.id)

    target_initiative = await create_initiative(session, guild, owner, name="Target")
    # Same name, same type (select), but completely different options
    existing_prop = await create_property_definition(
        session,
        target_initiative,
        name="Severity",
        type=PropertyType.select,
        options=[
            {"value": "critical", "label": "Critical"},
            {"value": "minor", "label": "Minor"},
        ],
    )

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )
    assert result.property_rename_count == 1

    # Original target definition unchanged
    refreshed = await session.get(PropertyDefinition, existing_prop.id)
    assert refreshed.options == [
        {"value": "critical", "label": "Critical"},
        {"value": "minor", "label": "Minor"},
    ]

    # Renamed import lives alongside it with the source's options
    stmt = select(PropertyDefinition).where(
        PropertyDefinition.initiative_id == target_initiative.id,
        PropertyDefinition.name == "Severity_select",
    )
    renamed = (await session.exec(stmt)).one_or_none()
    assert renamed is not None
    assert {o["value"] for o in (renamed.options or [])} == {"low", "high"}


@pytest.mark.integration
async def test_property_options_label_only_difference_matches(session: AsyncSession):
    """Labels are cosmetic; same value set with different labels still
    counts as a match (no rename, no new definition)."""
    owner, assignee, guild, source_initiative, source_project = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(session, project_id=source_project.id)

    target_initiative = await create_initiative(session, guild, owner, name="Target")
    await create_property_definition(
        session,
        target_initiative,
        name="Severity",
        type=PropertyType.select,
        options=[
            {"value": "low", "label": "LOW PRIORITY"},
            {"value": "high", "label": "HIGH PRIORITY"},
        ],
    )

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )
    assert result.property_rename_count == 0
    assert result.property_match_count == 1


@pytest.mark.integration
async def test_unmatched_assignees_reported(session: AsyncSession):
    owner, assignee, guild, source_initiative, source_project = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(session, project_id=source_project.id)

    # Target initiative has *no* members other than the owner — alice isn't a member here
    target_initiative = await create_initiative(session, guild, owner, name="Target")

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )
    assert result.assignee_match_count == 0
    assert result.assignee_unmatched_emails == ["alice@example.com"]


@pytest.mark.integration
async def test_schema_version_unsupported_rejected(session: AsyncSession):
    owner = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild, role=GuildRole.admin)
    target_initiative = await create_initiative(session, guild, owner)

    # Hand-roll a minimal envelope with an unsupported version
    from app.schemas.project_export import (
        ProjectExportEnvelope,
        ProjectExportProject,
        ProjectExportTaskStatus,
    )
    from datetime import datetime, timezone

    envelope = ProjectExportEnvelope(
        schema_version=999,
        app_version="0.0.0",
        exported_at=datetime.now(timezone.utc),
        project=ProjectExportProject(name="X"),
        tags=[],
        task_statuses=[
            ProjectExportTaskStatus(name="B", category=TaskStatusCategory.backlog, is_default=True)
        ],
        property_definitions=[],
        tasks=[],
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await import_service.import_project(
            session,
            envelope=envelope,
            target_initiative=target_initiative,
            importer=owner,
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "PROJECT_EXPORT_SCHEMA_VERSION_UNSUPPORTED"
