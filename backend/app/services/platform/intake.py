"""Open a case: turn something that happened into a task in a bound project.

One entry point, :func:`open_case`, used by every source — a rule that watched
the system, a person reporting something, a person asking for help.

The mechanics that matter, each forced by the tenancy model:

- It runs on **its own session and transaction**, on the system engine, so a
  case and whatever raised it commit independently.
- It **routes** into the operations guild's schema as ``guild_role="admin"``
  before it reads or writes anything there, and with **no user id**: the
  ``created_by`` trigger then stamps NULL, which is the truthful answer for a
  row nobody signed in created.
- **The binding decides where a case lands, not the submitter.** Reading a case
  stays with the bound project's initiative, exactly as reading any other task
  in that project does.
- It returns the new task's id, or ``None`` where nothing is bound. A
  deployment that has configured no binding calls this freely and it does
  nothing.

Repeats are folded into one case. The writer takes the latest case for a
``dedupe_key`` and, if it is still open and was last seen inside ``window``,
leaves it alone but stamps ``last_seen_at`` — so a sustained run produces one
case with a trail of recurrences rather than a case per event. A crossing whose
case was closed opens a new one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import CaseField, CASE_FIELD_TYPES, IntakeStream, STREAM_FIELDS
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.intake import DEDUPE_KEY_LENGTH, IntakeBinding, IntakeCase
from app.models.tenant.project import Project
from app.models.tenant.property import PropertyDefinition, PropertyType
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.property import PropertyValueInput
from app.services.tenant import properties as properties_service
from app.services.tenant import task_creation as task_creation_service

logger = logging.getLogger(__name__)

#: How long a repeat is folded into the open case before the writer says so
#: again. A case still being worked should not fill with one comment per event.
DEFAULT_RECURRENCE_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class CaseRefs:
    """What a case points at, as weak refs.

    Integer ids and a uuid string, never a resolved person: turning
    ``subject_user`` into somebody is a platform surface behind the platform
    capability, and reaching the content it names is break-glass. An erased
    account leaves a dangling id here rather than a preserved person.
    """

    subject_user: Optional[int] = None
    subject_guild: Optional[int] = None
    source_event: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    reported_at: Optional[datetime] = None
    severity: Optional[str] = None

    def as_fields(self) -> dict[CaseField, object]:
        """The non-empty refs, keyed by the field each is stored in."""
        named = {
            CaseField.subject_user: self.subject_user,
            CaseField.subject_guild: self.subject_guild,
            CaseField.source_event: self.source_event,
            CaseField.resource_type: self.resource_type,
            CaseField.resource_id: self.resource_id,
            CaseField.reported_at: self.reported_at,
            CaseField.severity: self.severity,
        }
        return {field: value for field, value in named.items() if value is not None}


@dataclass(frozen=True)
class CaseOutcome:
    """What ``open_case`` did."""

    #: The task the case lives in, whether opened now or already open.
    task_id: int
    #: False when a repeat landed in a case that was already open.
    opened: bool


async def operations_guild_id(session: AsyncSession) -> Optional[int]:
    """The guild this deployment routes operations work to, if any.

    Read on the session as given, before any guild routing. ``None`` — the
    value on every fresh and existing install — means this deployment routes
    nothing, and every caller treats that as a no-op rather than an error.
    """
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    return row.operations_guild_id if row is not None else None


async def _binding_for(
    session: AsyncSession, stream: IntakeStream
) -> Optional[IntakeBinding]:
    """The enabled binding for ``stream``, on an already-routed session."""
    return (
        await session.exec(
            select(IntakeBinding)
            .where(IntakeBinding.stream == stream.value)
            .where(IntakeBinding.enabled.is_(True))
            .execution_options(populate_existing=True)
        )
    ).first()


async def _hold_key(
    session: AsyncSession, *, guild_id: int, stream: IntakeStream, dedupe_key: str
) -> None:
    """Hold this key for the rest of the transaction.

    Two sources crossing the same line at the same moment queue here, so one
    opens the case and the other finds it. A transaction-scoped advisory lock,
    released by the commit or rollback that ends the transaction, and taken on
    the writer's own session rather than anywhere near the path being watched.

    The guild id is one half of the lock key, because advisory locks are
    cluster-wide where a schema is per-guild.
    """
    await session.exec(
        text("SELECT pg_advisory_xact_lock(:guild, hashtext(:key))").bindparams(
            guild=guild_id, key=f"{stream.value}:{dedupe_key}"
        )
    )


async def _open_case_for_key(
    session: AsyncSession, *, project_id: int, stream: IntakeStream, dedupe_key: str
) -> Optional[IntakeCase]:
    """The case this key already has open in this project, if there is one.

    The project is read through the task rather than off the case, because the
    task's column is where a case's work actually lives — a task somebody moved
    into another project is that project's case now, and this one has none.

    Whether it is still being worked is answered in the same query, from the
    task's own status category, so open-or-closed is never something two rows
    have to be kept in step about. A task in the trash counts as closed: there
    is nothing to add to.
    """
    row = (
        await session.exec(
            select(IntakeCase, TaskStatus.category)
            .join(Task, Task.id == IntakeCase.task_id)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(Task.project_id == project_id)
            .where(Task.deleted_at.is_(None))
            .where(IntakeCase.stream == stream.value)
            .where(IntakeCase.dedupe_key == dedupe_key)
            .order_by(IntakeCase.opened_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        return None
    case, category = row
    return None if category == TaskStatusCategory.done else case


async def _ensure_field_definitions(
    session: AsyncSession, *, initiative_id: int, stream: IntakeStream
) -> dict[CaseField, PropertyDefinition]:
    """The stream's case fields as property definitions on this initiative.

    A blueprint-created project already has them. One a team made by hand, or
    restructured, may not — and a case must not lose its references because of
    how its project was set up, so the missing ones are created here. Matching
    is by name; a definition of the same name with a different type is left
    alone and that field is skipped, because it is the initiative's field now.
    """
    wanted = STREAM_FIELDS[stream]
    existing = {
        definition.name: definition
        for definition in await session.exec(
            select(PropertyDefinition).where(
                PropertyDefinition.initiative_id == initiative_id,
                PropertyDefinition.name.in_([field.value for field in wanted]),
            )
        )
    }

    resolved: dict[CaseField, PropertyDefinition] = {}
    for field in wanted:
        definition = existing.get(field.value)
        expected = PropertyType(CASE_FIELD_TYPES[field])
        if definition is None:
            definition = PropertyDefinition(
                initiative_id=initiative_id, name=field.value, type=expected
            )
            session.add(definition)
        elif definition.type != expected:
            continue
        resolved[field] = definition
    await session.flush()
    return resolved


async def _record_refs(
    session: AsyncSession,
    *,
    task: Task,
    initiative_id: int,
    stream: IntakeStream,
    refs: CaseRefs,
) -> None:
    """Attach the case's references to the task as property values."""
    values = refs.as_fields()
    if not values:
        return
    definitions = await _ensure_field_definitions(
        session, initiative_id=initiative_id, stream=stream
    )
    inputs = [
        PropertyValueInput(
            property_id=definitions[field].id,
            value=value.isoformat() if isinstance(value, datetime) else value,
        )
        for field, value in values.items()
        if field in definitions
    ]
    if inputs:
        await properties_service.set_task_property_values(
            session, task, inputs, initiative_id
        )


async def _landing_status_id(
    session: AsyncSession, binding: IntakeBinding, project: Project
) -> Optional[int]:
    """The status a new case starts in, or ``None`` for the project's default.

    A binding's named status is checked against the project here rather than
    trusted: statuses get renamed, reordered and deleted by the team that owns
    the project, and a case belongs in that project's default column rather
    than nowhere at all.
    """
    if binding.default_status_id is None:
        return None
    named = (
        await session.exec(
            select(TaskStatus.id)
            .where(TaskStatus.id == binding.default_status_id)
            .where(TaskStatus.project_id == project.id)
        )
    ).first()
    if named is None:
        logger.warning(
            "intake binding %s names a status the project no longer has; "
            "filing in the project default",
            binding.id,
        )
    return named


async def open_case(
    stream: IntakeStream,
    *,
    title: str,
    body: Optional[str] = None,
    refs: Optional[CaseRefs] = None,
    dedupe_key: Optional[str] = None,
    window: timedelta = DEFAULT_RECURRENCE_WINDOW,
    now: Optional[datetime] = None,
) -> Optional[CaseOutcome]:
    """File ``stream``'s work as a task in the project bound to it.

    Returns ``None`` when this deployment has bound nothing for the stream —
    the state every install starts in — so a caller may call this
    unconditionally. Errors are not swallowed here: a caller that must not fail
    because of us (a rule watching the request path) runs this in the
    background and handles that itself.
    """
    # Imported here, not at module scope, so the session maker is read at call
    # time — the idiom the other system-engine callers use.
    from app.db.session import AdminSessionLocal

    moment = now or datetime.now(timezone.utc)
    if dedupe_key is not None and len(dedupe_key) > DEDUPE_KEY_LENGTH:
        raise ValueError("dedupe_key is longer than the column that stores it")

    async with AdminSessionLocal() as session:
        guild_id = await operations_guild_id(session)
        if guild_id is None:
            return None

        # Ids are unique only within a schema, so nothing cached from the
        # public read may survive into the routed one.
        session.expunge_all()
        await set_rls_context(session, guild_id=guild_id, guild_role="admin")

        binding = await _binding_for(session, stream)
        if binding is None:
            return None

        project = (
            await session.exec(
                select(Project)
                .where(Project.id == binding.project_id)
                .execution_options(populate_existing=True)
            )
        ).first()
        if project is None:
            logger.warning(
                "intake binding %s names a project that is gone; nothing filed",
                binding.id,
            )
            return None
        if project.archived_at is not None or project.deleted_at is not None:
            # Archived and trashed content takes no writes, so this would be
            # refused by the database. Said plainly here instead, and shown on
            # the settings page, rather than surfacing as a policy error.
            logger.warning(
                "intake binding %s names a project that is archived or trashed; "
                "nothing filed",
                binding.id,
            )
            return None

        if dedupe_key is not None:
            await _hold_key(
                session, guild_id=guild_id, stream=stream, dedupe_key=dedupe_key
            )
            existing = await _open_case_for_key(
                session,
                project_id=project.id,
                stream=stream,
                dedupe_key=dedupe_key,
            )
            if existing is not None:
                # Every occurrence is counted and moves ``last_seen_at``; the
                # window decides only how often the case is marked again, so a
                # run in progress is not annotated once per event.
                existing.occurrences += 1
                existing.last_seen_at = moment
                if existing.noted_at + window <= moment:
                    existing.noted_at = moment
                session.add(existing)
                await session.commit()
                return CaseOutcome(task_id=existing.task_id, opened=False)

        task = await task_creation_service.create_task_row(
            session,
            project=project,
            task_status_id=await _landing_status_id(session, binding, project),
            now=moment,
            title=title,
            description=body,
        )
        if refs is not None:
            await _record_refs(
                session,
                task=task,
                initiative_id=project.initiative_id,
                stream=stream,
                refs=refs,
            )
        # Every case gets a row, keyed or not, so "when did this stream last
        # open one" is read rather than inferred from the project's tasks.
        session.add(
            IntakeCase(
                stream=stream,
                task_id=task.id,
                dedupe_key=dedupe_key,
                opened_at=moment,
                last_seen_at=moment,
                noted_at=moment,
                occurrences=1,
            )
        )
        await session.commit()
        return CaseOutcome(task_id=task.id, opened=True)
