"""Import a previously-exported project envelope into the target instance.

See plan & ``project_export.py`` for the format. The algorithm:

1. Validate ``schema_version``.
2. Resolve the target initiative + its guild + member emails.
3. Create the ``Project`` (importer is owner; rename on collision).
4. Bulk-create per-project task statuses; build ``name → id`` map.
5. Upsert tags by ``(guild_id, name)``; build ``name → id`` map; attach
   to project via ``project_tags``.
6. Upsert property definitions by ``(initiative_id, name)``. On type
   collision, create a new definition named ``<name>_<type>`` instead
   of mutating the target's existing one.
7. Insert each task; resolve status / tag / assignee / property refs
   via the maps; insert subtasks and property values.
8. Return :class:`ProjectImportResult` so the UI can warn about dropped
   assignees etc.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.messages import ProjectExportMessages
from app.db.session import reapply_rls_context
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project, ProjectPermission, ProjectPermissionLevel
from app.models.property import PropertyDefinition, PropertyType, TaskPropertyValue
from app.models.tag import ProjectTag, Tag, TaskTag
from app.models.task import Subtask, Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.models.user import User
from app.schemas.project_export import (
    MIN_SUPPORTED_IMPORT_VERSION,
    SCHEMA_VERSION,
    ProjectExportEnvelope,
    ProjectExportPropertyValue,
    ProjectExportTask,
    ProjectImportResult,
)


async def import_project(
    session: AsyncSession,
    *,
    envelope: ProjectExportEnvelope,
    target_initiative: Initiative,
    importer: User,
) -> ProjectImportResult:
    """Materialize ``envelope`` as a new project under ``target_initiative``.

    Caller is responsible for permission checks (the user must be allowed
    to create projects in the target initiative). RLS context must
    already point at the target guild.
    """
    if not (MIN_SUPPORTED_IMPORT_VERSION <= envelope.schema_version <= SCHEMA_VERSION):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectExportMessages.SCHEMA_VERSION_UNSUPPORTED,
        )
    if not envelope.task_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectExportMessages.NO_TASK_STATUSES,
        )

    initiative_member_emails = await _load_initiative_member_emails(
        session, initiative_id=target_initiative.id
    )
    target_guild_id = target_initiative.guild_id
    if target_guild_id is None:
        # Initiatives are created with a guild (services/initiatives.py
        # requires it). Reaching here means data corruption, not user
        # input — fail loudly rather than create guild-less tags that
        # would silently leak across guilds.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ProjectExportMessages.INITIATIVE_NOT_FOUND,
        )

    # 1. Project row (rename on collision)
    project_name = await _unique_project_name(
        session,
        initiative_id=target_initiative.id,
        desired_name=envelope.project.name,
    )
    project = Project(
        name=project_name,
        icon=envelope.project.icon,
        description=envelope.project.description,
        is_template=envelope.project.is_template,
        is_archived=envelope.project.is_archived,
        owner_id=importer.id,
        initiative_id=target_initiative.id,
        guild_id=target_guild_id,
    )
    session.add(project)
    await session.flush()  # populate project.id

    # Owner permission row (matches the `create_project` flow's invariant)
    session.add(
        ProjectPermission(
            project_id=project.id,
            user_id=importer.id,
            guild_id=target_guild_id,
            level=ProjectPermissionLevel.owner,
        )
    )

    # 2. Task statuses → name → id map
    status_name_to_id: dict[str, int] = {}
    default_status_id: int | None = None
    for s in envelope.task_statuses:
        status_row = TaskStatus(
            project_id=project.id,
            guild_id=target_guild_id,
            name=s.name,
            category=s.category,
            position=s.position,
            color=s.color,
            icon=s.icon,
            is_default=s.is_default,
        )
        session.add(status_row)
        await session.flush()
        status_name_to_id[s.name] = status_row.id
        if s.is_default and default_status_id is None:
            default_status_id = status_row.id
    if default_status_id is None:
        # First backlog-category status, else the first one
        for s in envelope.task_statuses:
            if s.category == TaskStatusCategory.backlog:
                default_status_id = status_name_to_id[s.name]
                break
        if default_status_id is None and envelope.task_statuses:
            default_status_id = status_name_to_id[envelope.task_statuses[0].name]

    # 3. Tags → name → id map; attach to project
    tag_name_to_id: dict[str, int] = {}
    tag_create_count = 0
    tag_match_count = 0
    for t in envelope.tags:
        tag_id = await _ensure_tag(
            session,
            guild_id=target_guild_id,
            name=t.name,
            color=t.color,
        )
        if tag_id.created:
            tag_create_count += 1
        else:
            tag_match_count += 1
        tag_name_to_id[t.name] = tag_id.id
        session.add(ProjectTag(project_id=project.id, tag_id=tag_id.id))

    # 4. Property definitions → (name, type) → id map
    existing_props = await _load_initiative_properties(
        session, initiative_id=target_initiative.id
    )
    prop_key_to_id: dict[tuple[str, PropertyType], int] = {}
    property_create_count = 0
    property_match_count = 0
    property_rename_count = 0
    for pd in envelope.property_definitions:
        match_existing = existing_props.get(pd.name)
        if match_existing is not None and match_existing.type == pd.type:
            prop_key_to_id[(pd.name, pd.type)] = match_existing.id
            property_match_count += 1
            continue
        # Either no match, or name match with type mismatch → create new
        target_name = pd.name
        if match_existing is not None and match_existing.type != pd.type:
            target_name = await _unique_property_name(
                session,
                initiative_id=target_initiative.id,
                desired_name=f"{pd.name}_{pd.type.value}",
            )
            property_rename_count += 1
        new_def = PropertyDefinition(
            initiative_id=target_initiative.id,
            name=target_name,
            type=pd.type,
            position=pd.position,
            color=pd.color,
            options=pd.options,
        )
        session.add(new_def)
        await session.flush()
        prop_key_to_id[(pd.name, pd.type)] = new_def.id
        # Track for subsequent collision-renames within this import
        existing_props[target_name] = new_def
        property_create_count += 1

    # 5. Tasks
    assignee_match_count = 0
    unmatched_emails: set[str] = set()
    for t in envelope.tasks:
        matched = await _import_task(
            session,
            envelope_task=t,
            project_id=project.id,
            guild_id=target_guild_id,
            importer_id=importer.id,
            status_name_to_id=status_name_to_id,
            default_status_id=default_status_id,
            tag_name_to_id=tag_name_to_id,
            prop_key_to_id=prop_key_to_id,
            initiative_member_emails=initiative_member_emails,
            unmatched_email_sink=unmatched_emails,
        )
        assignee_match_count += matched

    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(project)

    return ProjectImportResult(
        project_id=project.id,
        project_name=project.name,
        task_count=len(envelope.tasks),
        tag_create_count=tag_create_count,
        tag_match_count=tag_match_count,
        property_create_count=property_create_count,
        property_match_count=property_match_count,
        property_rename_count=property_rename_count,
        assignee_match_count=assignee_match_count,
        assignee_unmatched_emails=sorted(unmatched_emails),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TagResolved:
    __slots__ = ("id", "created")

    def __init__(self, *, id: int, created: bool) -> None:
        self.id = id
        self.created = created


async def _ensure_tag(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str,
    color: str,
) -> _TagResolved:
    """Find a tag by ``(guild_id, name)`` or create it.

    ``guild_id`` is intentionally non-optional: a ``None`` here would
    silently match guild-less tags (``WHERE guild_id IS NULL``) and
    cross-pollinate across guilds. Callers must guarantee a real guild
    before reaching this helper.
    """
    stmt = select(Tag).where(Tag.guild_id == guild_id, Tag.name == name)
    existing = (await session.exec(stmt)).one_or_none()
    if existing is not None:
        return _TagResolved(id=existing.id, created=False)
    tag = Tag(guild_id=guild_id, name=name, color=color)
    session.add(tag)
    await session.flush()
    return _TagResolved(id=tag.id, created=True)


async def _unique_project_name(
    session: AsyncSession, *, initiative_id: int, desired_name: str
) -> str:
    """Append ' (imported)' / ' (imported 2)' until the name is free in
    the target initiative. Soft, non-fatal collision handling."""
    stmt = select(Project.name).where(Project.initiative_id == initiative_id)
    existing = {row for row in (await session.exec(stmt)).all()}
    if desired_name not in existing:
        return desired_name
    candidate = f"{desired_name} (imported)"
    n = 2
    while candidate in existing:
        candidate = f"{desired_name} (imported {n})"
        n += 1
    return candidate


async def _unique_property_name(
    session: AsyncSession, *, initiative_id: int, desired_name: str
) -> str:
    stmt = select(PropertyDefinition.name).where(
        PropertyDefinition.initiative_id == initiative_id
    )
    existing = {row for row in (await session.exec(stmt)).all()}
    if desired_name not in existing:
        return desired_name
    n = 2
    while f"{desired_name}_{n}" in existing:
        n += 1
    return f"{desired_name}_{n}"


async def _load_initiative_member_emails(
    session: AsyncSession, *, initiative_id: int
) -> dict[str, int]:
    """Map ``email → user_id`` for the target initiative's members.

    Per the locked scope: assignees are matched against members of the
    *initiative*, not the wider guild. ``User.email`` is a decryption
    property, not a column, so we load the User row and read the
    property in Python rather than projecting the column.
    """
    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
    )
    users = (await session.exec(stmt)).all()
    return {user.email: user.id for user in users if user.email}


async def _load_initiative_properties(
    session: AsyncSession, *, initiative_id: int
) -> dict[str, PropertyDefinition]:
    stmt = select(PropertyDefinition).where(
        PropertyDefinition.initiative_id == initiative_id
    )
    return {pd.name: pd for pd in (await session.exec(stmt)).all()}


async def _import_task(
    session: AsyncSession,
    *,
    envelope_task: ProjectExportTask,
    project_id: int,
    guild_id: int | None,
    importer_id: int,
    status_name_to_id: dict[str, int],
    default_status_id: int | None,
    tag_name_to_id: dict[str, int],
    prop_key_to_id: dict[tuple[str, PropertyType], int],
    initiative_member_emails: dict[str, int],
    unmatched_email_sink: set[str],
) -> int:
    """Insert one task, its subtasks, tags, assignees, and property
    values. Returns the number of distinct assignees matched & linked.
    """
    status_id = status_name_to_id.get(envelope_task.status_name) or default_status_id
    if status_id is None:
        # Should be unreachable because we require non-empty
        # task_statuses on the envelope, but bail loudly if it happens.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectExportMessages.NO_TASK_STATUSES,
        )

    task = Task(
        project_id=project_id,
        guild_id=guild_id,
        task_status_id=status_id,
        title=envelope_task.title,
        description=envelope_task.description,
        priority=envelope_task.priority,
        start_date=envelope_task.start_date,
        due_date=envelope_task.due_date,
        recurrence=envelope_task.recurrence,
        recurrence_strategy=envelope_task.recurrence_strategy,
        recurrence_occurrence_count=envelope_task.recurrence_occurrence_count,
        sort_order=envelope_task.sort_order,
        is_archived=envelope_task.is_archived,
        created_by_id=importer_id,
    )
    session.add(task)
    await session.flush()

    # Subtasks
    for sub in envelope_task.subtasks:
        session.add(
            Subtask(
                task_id=task.id,
                guild_id=guild_id,
                content=sub.content,
                is_completed=sub.is_completed,
                position=sub.position,
            )
        )

    # Tag links — match-or-create against the target guild for any tag
    # that wasn't already in the project-level set (tasks can have tags
    # the project itself doesn't carry).
    for task_tag in envelope_task.tags:
        tid = tag_name_to_id.get(task_tag.name)
        if tid is None:
            resolved = await _ensure_tag(
                session,
                guild_id=guild_id,
                name=task_tag.name,
                color=task_tag.color,
            )
            tid = resolved.id
            tag_name_to_id[task_tag.name] = tid
        session.add(TaskTag(task_id=task.id, tag_id=tid))

    # Assignees: match by email against initiative members; drop misses
    seen_user_ids: set[int] = set()
    for email in envelope_task.assignee_emails:
        uid = initiative_member_emails.get(email)
        if uid is None:
            unmatched_email_sink.add(email)
            continue
        if uid in seen_user_ids:
            continue
        seen_user_ids.add(uid)
        session.add(TaskAssignee(task_id=task.id, user_id=uid, guild_id=guild_id))

    # Property values
    for pv in envelope_task.property_values:
        prop_id = prop_key_to_id.get((pv.property_name, pv.property_type))
        if prop_id is None:
            # Defensive: skip values whose property couldn't be resolved
            continue
        column_kwargs = _decode_property_value(pv, initiative_member_emails)
        if column_kwargs is None:
            continue  # user_reference with no matching email — skip silently
        session.add(
            TaskPropertyValue(task_id=task.id, property_id=prop_id, **column_kwargs)
        )

    return len(seen_user_ids)


def _decode_property_value(
    pv: ProjectExportPropertyValue,
    initiative_member_emails: dict[str, int],
) -> dict[str, Any] | None:
    """Convert an envelope property value back to the typed column kwargs.

    Returns ``None`` if the value is a user reference whose email isn't a
    member of the target initiative — caller skips the row silently.
    """
    t = pv.property_type
    if t in (PropertyType.text, PropertyType.url, PropertyType.select):
        return {"value_text": pv.value_text}
    if t == PropertyType.number:
        return {"value_number": pv.value_number}
    if t == PropertyType.checkbox:
        return {"value_boolean": pv.value_boolean}
    if t == PropertyType.date:
        return {"value_date": _parse_date(pv.value_text)}
    if t == PropertyType.datetime:
        return {"value_datetime": _parse_datetime(pv.value_text)}
    if t == PropertyType.multi_select:
        return {"value_json": pv.value_json}
    if t == PropertyType.user_reference:
        if not pv.value_email:
            return {"value_user_id": None}
        uid = initiative_member_emails.get(pv.value_email)
        if uid is None:
            # Drop the value rather than the whole task; the UI will
            # render this property as "—" for the task.
            return None
        return {"value_user_id": uid}
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
