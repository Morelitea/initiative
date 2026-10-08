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
from typing import TYPE_CHECKING, Optional, Sequence

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import (
    CASE_FIELD_TYPES,
    STREAM_FIELDS,
    CaseField,
    IntakeStream,
    meta,
)
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import DEDUPE_KEY_LENGTH, IntakeBinding, IntakeCase
from app.models.tenant.project import Project
from app.models.tenant.property import PropertyDefinition, PropertyType
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.property import PropertyValueInput
from app.services.platform import case_activity
from app.services.tenant import properties as properties_service
from app.services.tenant import task_creation as task_creation_service
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.platform.evidence import PreparedEvidence

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
class CaseFiler:
    """The person who filed a case, when a person did.

    What connects them to it — so they can follow it — and their own words:
    what they called it, and what they said, which opens the case's
    conversation with them rather than being folded into a description the
    people working it will rewrite.
    """

    user_id: int
    subject: str
    words: str


@dataclass(frozen=True)
class CaseOutcome:
    """What ``open_case`` did."""

    #: The task the case lives in, whether opened now or already open.
    task_id: int
    #: False when a repeat landed in a case that was already open.
    opened: bool
    #: The case's own row.
    case_id: int = 0


async def operations_guild_id(session: AsyncSession) -> Optional[int]:
    """The guild this deployment routes operations work to, if any.

    Read on the session as given, before any guild routing. ``None`` — the
    value on every fresh and existing install — means this deployment routes
    nothing, and every caller treats that as a no-op rather than an error.
    """
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    return row.operations_guild_id if row is not None else None


async def configured_operations_guild_id() -> Optional[int]:
    """:func:`operations_guild_id`, read on a platform system session."""
    async with cohorts.system_session(None) as session:
        return await operations_guild_id(session)


async def contact_for(session: AsyncSession, stream: IntakeStream) -> Optional[str]:
    """Who somebody is told to contact about ``stream``.

    The stream's own address, else the deployment's general one, else
    ``None`` — in which case the notice names nobody. Never another stream's
    address: each inbox answers its own kind of work, and the general address
    is the catch-all. Readable on any session, since ``app_settings`` is.
    """
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        return None
    return (row.intake_contacts or {}).get(stream.value) or row.intake_general_contact


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


async def stream_is_bound(stream: IntakeStream) -> bool:
    """Whether anything is set up to receive this stream's cases.

    What a surface asks before offering to send something: a form that can only
    answer "nowhere to send it" is worse than the surface that replaces it.
    Runs on a system session of its own from the operations guild's cohort,
    routed into it, the way :func:`open_case` does, because the binding lives
    there.
    """
    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return False
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        binding = await _binding_for(session, stream)
        if binding is None:
            return False
        # The same test :func:`open_case` applies before it files anything: a
        # project that is archived or in the trash takes no new cases.
        project = (
            await session.exec(
                select(Project.archived_at, Project.deleted_at).where(
                    Project.id == binding.project_id
                )
            )
        ).first()
        return project is not None and project[0] is None and project[1] is None


class CaseCapReached(Exception):
    """The filer already has as many of the stream's cases open as it allows."""


async def _open_cases_filed_by(
    session: AsyncSession, *, user_id: int, stream: IntakeStream
) -> int:
    """How many of ``stream``'s cases ``user_id`` filed that are still open.

    On the writer's own routed session, under the filer's lock, so the count
    and the case it admits are one decision. A case is open while its task is
    out of the trash and short of a ``done`` status — the same test a repeat
    uses to find the case it joins.
    """
    count = (
        await session.exec(
            select(func.count())
            .select_from(IntakeCase)
            .join(Task, Task.id == IntakeCase.task_id)
            .join(TaskStatus, TaskStatus.id == Task.task_status_id)
            .where(IntakeCase.filer_user_id == user_id)
            .where(IntakeCase.stream == stream.value)
            .where(Task.deleted_at.is_(None))
            .where(TaskStatus.category != TaskStatusCategory.done)
        )
    ).one()
    return int(count)


async def _starting_state(
    session: AsyncSession,
    stream: IntakeStream,
    binding: IntakeBinding,
    status_id: Optional[int],
) -> str:
    """The state a case landing in ``status_id`` shows whoever filed it."""
    from app.services.platform.tickets import derive_state

    category = (
        await session.exec(
            select(TaskStatus.category).where(TaskStatus.id == status_id)
        )
    ).one_or_none()
    return derive_state(
        category=category or TaskStatusCategory.todo,
        status_id=status_id,
        awaiting_status_id=binding.awaiting_filer_status_id,
        stream=stream,
    ).value


async def _hold_key(
    session: AsyncSession, *, guild_id: int, stream: IntakeStream, dedupe_key: str
) -> None:
    """Hold this key for the rest of the transaction.

    Two sources crossing the same line at the same moment queue here, so one
    opens the case and the other finds it. A transaction-scoped advisory lock,
    released by the commit or rollback that ends the transaction, and taken on
    the writer's own session rather than anywhere near the path being watched.

    The guild id is part of the lock key, because advisory locks span the
    database where a schema is per-guild.
    """
    await advisory_lock(
        session,
        LockNamespace.INTAKE_CASE,
        f"{guild_id}:{stream.value}:{dedupe_key}",
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
        await properties_service.write_values(
            session, task, inputs, initiative_id=initiative_id
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
    filer: Optional[CaseFiler] = None,
    detail: Optional[str] = None,
    evidence: Sequence["PreparedEvidence"] = (),
    evidence_by: Optional[int] = None,
) -> Optional[CaseOutcome]:
    """File ``stream``'s work as a task in the project bound to it.

    Returns ``None`` when this deployment has bound nothing for the stream —
    the state every install starts in — so a caller may call this
    unconditionally. Errors are not swallowed here: a caller that must not fail
    because of us (a rule watching the request path) runs this in the
    background and handles that itself.

    ``filer`` names the person filing, when a person is. A new case records
    them and opens with their words, said to them; a repeat that lands in a
    case already open says what was new on the case instead. The stream's cap
    on one filer's open cases is checked under a lock on that filer, in the
    transaction that opens the case, and ``CaseCapReached`` is raised past it.

    ``detail`` is what this occurrence brings beyond the description — a new
    reporter's words. A repeat notes it every time; a repeat bringing nothing
    is noted once per window. An automatic case passes none, so its unchanged
    description is never taken for news.

    ``evidence`` is what was attached, already held to the stream's policy
    (``app.services.platform.evidence.prepare``). It is stored with the case,
    in the same transaction, beside the opening words when there are some, and
    as ``evidence_by``'s — the filer's when there is one.
    """
    from app.services.platform import evidence as evidence_service

    attached_by = (
        evidence_by
        if evidence_by is not None
        else (filer.user_id if filer is not None else None)
    )
    moment = now or datetime.now(timezone.utc)
    if dedupe_key is not None and len(dedupe_key) > DEDUPE_KEY_LENGTH:
        raise ValueError("dedupe_key is longer than the column that stores it")

    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return None
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))

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
                window_passed = existing.noted_at + window <= moment
                if window_passed:
                    existing.noted_at = moment
                session.add(existing)
                # What a repeat brings with it is noted every time — it is
                # somebody's words, not one more of the same event — and a
                # repeat bringing nothing is noted once per window.
                news = filer.words if filer is not None else detail
                if news or window_passed:
                    await case_activity.post(
                        session,
                        task_id=existing.task_id,
                        kind=case_activity.ActivityKind.repeat,
                        text=case_activity.repeat_text(
                            occurrences=existing.occurrences, detail=news
                        ),
                    )
                stored = evidence_service.store(
                    session,
                    guild_id=guild_id,
                    prepared=evidence,
                    created_by=attached_by,
                    case_id=existing.id,
                )
                try:
                    await session.commit()
                except BaseException:
                    evidence_service.discard(guild_id, stored)
                    raise
                return CaseOutcome(
                    task_id=existing.task_id, opened=False, case_id=int(existing.id)
                )

        cap = meta(stream).max_open_per_filer
        if filer is not None and cap is not None:
            # Held for the rest of the transaction, so two filings at once
            # queue here and the second counts the first's case.
            await _hold_key(
                session,
                guild_id=guild_id,
                stream=stream,
                dedupe_key=f"filer:{filer.user_id}",
            )
            held = await _open_cases_filed_by(
                session, user_id=filer.user_id, stream=stream
            )
            if held >= cap:
                raise CaseCapReached

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
        case = IntakeCase(
            stream=stream,
            task_id=task.id,
            dedupe_key=dedupe_key,
            opened_at=moment,
            last_seen_at=moment,
            noted_at=moment,
            occurrences=1,
            filer_user_id=filer.user_id if filer is not None else None,
            filer_subject=filer.subject if filer is not None else None,
            # Where its filer starts, so the first move after it is news
            # to them however soon it comes.
            filer_notified_state=(
                await _starting_state(session, stream, binding, task.task_status_id)
                if filer is not None
                else None
            ),
        )
        session.add(case)
        opening: Optional[Comment] = None
        if filer is not None:
            # Their words open the conversation with them, under their name.
            # Named explicitly: the routing carries no user, so the trigger
            # would otherwise leave the author empty.
            opening = Comment(
                task_id=task.id,
                content=filer.words,
                created_by=filer.user_id,
                audience=CommentAudience.filer,
            )
            session.add(opening)
        await session.flush()
        stored = evidence_service.store(
            session,
            guild_id=guild_id,
            prepared=evidence,
            created_by=attached_by,
            case_id=case.id,
            comment_id=opening.id if opening is not None else None,
        )
        try:
            await session.commit()
        except BaseException:
            evidence_service.discard(guild_id, stored)
            raise
        return CaseOutcome(task_id=task.id, opened=True, case_id=int(case.id))


async def add_filer_reply(
    *,
    guild_id: int,
    task_id: int,
    filer: User,
    words: str,
    stream: IntakeStream,
    evidence: Sequence["PreparedEvidence"] = (),
) -> bool:
    """Write a filer's answer on their case, said to them like the rest of the
    conversation, and move a case that is waiting on them. Returns whether it
    was taken.

    ``guild_id`` is the operations community the caller read the case in,
    through the filer's own access. The case is read again here, locked, so
    the answer lands only on a case that is still theirs and still open, and
    the "waiting on you" it moves on is the case's state now rather than when
    the page was read. Written on the writer's session, routed by ``guild_id``
    alone; the author is named explicitly, since the routing carries no user.
    The task's assignees hear of it as they would of any comment on the task.
    ``evidence`` is stored with the answer, in the same transaction.
    """
    from app.services.platform import evidence as evidence_service
    from app.services.platform import ticket_stream
    from app.services.platform.tickets import FilerState, derive_state
    from app.services.tenant.comments import notify_task_assignees

    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        found = (
            await session.exec(
                select(Task, IntakeCase.id)
                .join(IntakeCase, IntakeCase.task_id == Task.id)
                .where(Task.id == task_id)
                .where(IntakeCase.filer_user_id == filer.id)
                .with_for_update(of=Task)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if found is None:
            return False
        task, case_id = found
        category = (
            await session.exec(
                select(TaskStatus.category).where(TaskStatus.id == task.task_status_id)
            )
        ).one_or_none()
        binding = await _binding_for(session, stream)
        state = derive_state(
            category=category or TaskStatusCategory.todo,
            status_id=task.task_status_id,
            awaiting_status_id=(
                binding.awaiting_filer_status_id if binding is not None else None
            ),
            stream=stream,
            trashed=task.deleted_at is not None,
        )
        if state is FilerState.closed:
            return False
        comment = Comment(
            task_id=task_id,
            content=words,
            created_by=filer.id,
            audience=CommentAudience.filer,
        )
        session.add(comment)
        await session.flush()
        stored = evidence_service.store(
            session,
            guild_id=guild_id,
            prepared=evidence,
            created_by=filer.id,
            case_id=case_id,
            comment_id=comment.id,
        )
        await notify_task_assignees(session, comment=comment, author=filer, task=task)
        # Their other tabs follow the same conversation.
        ticket_stream.queue_ticket_signal(session, filer.id)
        active = binding.active_status_id if binding is not None else None
        if state is FilerState.waiting_on_you and active is not None:
            # Checked against the task's own project: a case moved elsewhere
            # keeps its status rather than borrowing one.
            belongs = (
                await session.exec(
                    select(TaskStatus.id)
                    .where(TaskStatus.id == active)
                    .where(TaskStatus.project_id == task.project_id)
                )
            ).first()
            if belongs is not None:
                task.task_status_id = active
                session.add(task)
        try:
            await session.commit()
        except BaseException:
            evidence_service.discard(guild_id, stored)
            raise
    return True
