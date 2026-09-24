"""Import a previously-exported project envelope into the target instance.

See plan & ``project_export.py`` for the format. The algorithm:

1. Validate ``schema_version``.
2. Resolve the target initiative + its guild + member handles.
3. Create the ``Project`` (importer is owner; rename on collision).
4. Bulk-create per-project task statuses; build ``name → id`` map.
5. Upsert tags by name; build ``name → id`` map; attach
   to project via ``project_tags``.
6. Upsert property definitions by ``(initiative_id, name)``. On type
   collision, create a new definition named ``<name>_<type>`` instead
   of mutating the target's existing one.
7. Insert each task; resolve status / tag / assignee / property refs
   via the maps; insert property values.
8. Return :class:`ProjectImportResult` so the UI can warn about dropped
   assignees etc.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.messages import ProjectExportMessages
from app.core.search import SearchEntityType
from app.models.tenant.comment import Comment
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.property import (
    PropertyType,
    TaskPropertyValue,
)
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.platform.user import User
from app.schemas.tenant.project_export import (
    MIN_SUPPORTED_IMPORT_VERSION,
    SCHEMA_VERSION,
    ProjectExportComment,
    ProjectExportEnvelope,
    ProjectExportTask,
    ProjectImportResult,
)
from app.schemas.tenant.task import mint_checklist_item_id
from app.services.import_engine.context import ImportContext
from app.services.import_engine.links import links_to_pages
from app.services.import_engine.references import (
    has_source_references,
    note_or_settle,
)
from app.services.import_engine.people import (
    PeopleMap,
    initiative_member_id,
    quoted_account,
)
from app.services.tenant import task_completion
from app.services.tenant.task_statuses import defaults_for_category
from app.services.import_engine.common import (
    decode_property_value,
    ensure_tag,
    load_initiative_member_handles,
    handle_key,
    resolve_property_definitions,
)
from app.services.tenant import tags as tags_service


async def import_project(
    session: AsyncSession,
    *,
    envelope: ProjectExportEnvelope,
    target_initiative: Initiative,
    importer: User,
    context: ImportContext | None = None,
) -> ProjectImportResult:
    """Materialize ``envelope`` as a new project under ``target_initiative``.

    Caller is responsible for permission checks (the user must be allowed
    to create projects in the target initiative) AND for committing — this
    function only flushes, so the import engine can compose it inside a
    larger transaction (per-chunk backup commits). RLS context must
    already point at the target guild.

    ``context`` is what the job knows and this envelope does not: the link
    collector, which each task registers itself with under the
    ``external_ref`` its envelope gave so the deferred pass can resolve the
    links it asserts — nothing resolves here, because the far end is usually
    in an entry that has not been applied yet — and the people map, which
    says which account each handle in it turned out to be.
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

    initiative_member_handles = await load_initiative_member_handles(
        session, initiative_id=target_initiative.id
    )
    # The same roster read the other way round. Assignment is gated on
    # membership however the handle was resolved, and a mapped account is
    # known by its id rather than by a handle to look up.
    initiative_member_ids = frozenset(initiative_member_handles.values())

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
        archived_at=envelope.project.archived_at,
        start_date=envelope.project.start_date,
        end_date=envelope.project.end_date,
        initiative_id=target_initiative.id,
    )
    session.add(project)
    await session.flush()  # populate project.id

    # Owner permission row (matches the `create_project` flow's invariant)
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=importer.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            initiative_id=project.initiative_id,
        )
    )

    # 2. Task statuses → name → id map
    status_name_to_id: dict[str, int] = {}
    status_id_to_category: dict[int, TaskStatusCategory] = {}
    default_status_id: int | None = None
    for s in envelope.task_statuses:
        default_color, default_icon = defaults_for_category(s.category)
        status_row = TaskStatus(
            project_id=project.id,
            name=s.name,
            category=s.category,
            position=s.position,
            color=s.color or default_color,
            icon=s.icon or default_icon,
            is_default=s.is_default,
        )
        session.add(status_row)
        await session.flush()
        status_name_to_id[s.name] = status_row.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        status_id_to_category[status_row.id] = s.category  # ty: ignore[invalid-assignment] — persisted row, id is set
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
        tag_id = await ensure_tag(
            session,
            name=t.name,
            color=t.color,
        )
        if tag_id.created:
            tag_create_count += 1
        else:
            tag_match_count += 1
        tag_name_to_id[t.name] = tag_id.id
        session.add(
            tags_service.tag_edge(
                tags_service.TAG_LINKS["project"], project.id, tag_id.id
            )
        )

    # 4. Property definitions → (name, type) → id map (shared conventions:
    # match by name+type with option compatibility, rename on collision).
    # A property unticked on the review is not declared at all; its values
    # then resolve to nothing and are skipped below, with the rest.
    excluded = context.excluded_properties if context is not None else frozenset()
    resolved_props = await resolve_property_definitions(
        session,
        initiative_id=target_initiative.id,
        definitions=[
            definition
            for definition in envelope.property_definitions
            if definition.name not in excluded
        ],
    )
    prop_key_to_id = resolved_props.key_to_id
    property_create_count = resolved_props.created
    property_match_count = resolved_props.matched
    property_rename_count = len(resolved_props.renamed)

    # 5. Tasks
    assignee_match_count = 0
    comment_count = 0
    unmatched_handles: set[str] = set()
    for t in envelope.tasks:
        matched, comments_made = await _import_task(
            session,
            envelope_task=t,
            project_id=project.id,
            importer_id=importer.id,
            status_name_to_id=status_name_to_id,
            status_id_to_category=status_id_to_category,
            default_status_id=default_status_id,
            tag_name_to_id=tag_name_to_id,
            prop_key_to_id=prop_key_to_id,
            initiative_member_handles=initiative_member_handles,
            initiative_member_ids=initiative_member_ids,
            unmatched_handle_sink=unmatched_handles,
            context=context,
        )
        assignee_match_count += matched
        comment_count += comments_made

    await session.flush()

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
        assignee_unmatched_handles=sorted(unmatched_handles),
        comment_count=comment_count,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _import_task(
    session: AsyncSession,
    *,
    envelope_task: ProjectExportTask,
    project_id: int,
    importer_id: int,
    status_name_to_id: dict[str, int],
    status_id_to_category: dict[int, TaskStatusCategory],
    default_status_id: int | None,
    tag_name_to_id: dict[str, int],
    prop_key_to_id: dict[tuple[str, PropertyType], int],
    initiative_member_handles: dict[str, int],
    initiative_member_ids: frozenset[int],
    unmatched_handle_sink: set[str],
    context: ImportContext | None = None,
) -> tuple[int, int]:
    """Insert one task, its checklist, tags, assignees, property values and
    comments. Returns (assignees matched & linked, comments written).
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
        task_status_id=status_id,
        title=envelope_task.title,
        description=_link_mentions(
            envelope_task.description,
            envelope_task.mention_handles,
            context=context,
            initiative_member_handles=initiative_member_handles,
        ),
        priority=envelope_task.priority,
        start_date=envelope_task.start_date,
        due_date=envelope_task.due_date,
        recurrence=envelope_task.recurrence,
        recurrence_strategy=envelope_task.recurrence_strategy,
        recurrence_occurrence_count=envelope_task.recurrence_occurrence_count,
        position=envelope_task.position,
        archived_at=envelope_task.archived_at,
        completed_at=envelope_task.completed_at,
        created_by=importer_id,
        # When the work was written down, where the envelope says so. An
        # envelope that carries neither leaves the model's own default — the
        # moment of the import, which is the only time this row can honestly
        # claim. ``None`` would be a lie of a different kind: the column is
        # NOT NULL and every reader treats it as "when this appeared".
        **_timestamps(envelope_task),
        checklist=[
            {
                "id": mint_checklist_item_id(),
                "text": item.text,
                "done": item.done,
            }
            for item in envelope_task.checklist
        ],
    )
    # A restore keeps the completion time the envelope carries; envelopes taken
    # before the field existed carry none, so it's derived from the restored
    # status instead. Either way the timestamp ends up agreeing with the status.
    task_completion.sync_completed_at(
        task,
        status_id_to_category.get(status_id),
        now=datetime.now(timezone.utc),
    )
    session.add(task)
    await session.flush()

    # Tag links — match-or-create against the target guild for any tag
    # that wasn't already in the project-level set (tasks can have tags
    # the project itself doesn't carry).
    for task_tag in envelope_task.tags:
        tid = tag_name_to_id.get(task_tag.name)
        if tid is None:
            resolved = await ensure_tag(
                session,
                name=task_tag.name,
                color=task_tag.color,
            )
            tid = resolved.id
            tag_name_to_id[task_tag.name] = tid
        session.add(tags_service.tag_edge(tags_service.TAG_LINKS["task"], task.id, tid))

    # Assignees: the account a person mapped the handle to, else a member
    # whose handle is the same string — and a member of this initiative
    # either way (see ``people.initiative_member_id``). Misses are dropped
    # and counted.
    seen_user_ids: set[int] = set()
    for handle in envelope_task.assignee_handles:
        uid = initiative_member_id(
            handle,
            people=context.people if context is not None else PeopleMap(),
            member_handles=initiative_member_handles,
            member_ids=initiative_member_ids,
        )
        if uid is None:
            unmatched_handle_sink.add(handle)
            continue
        if uid in seen_user_ids:
            continue
        seen_user_ids.add(uid)
        session.add(
            TaskAssignee(
                task_id=task.id,
                user_id=uid,
            )
        )

    # Property values
    for pv in envelope_task.property_values:
        prop_id = prop_key_to_id.get((pv.property_name, pv.property_type))
        if prop_id is None:
            # Defensive: skip values whose property couldn't be resolved
            continue
        column_kwargs = decode_property_value(
            pv,
            initiative_member_handles,
            people=context.people if context is not None else None,
        )
        if column_kwargs is None:
            continue  # user_reference with no matching handle — skip silently
        session.add(
            TaskPropertyValue(task_id=task.id, property_id=prop_id, **column_kwargs)
        )

    if context is not None and links_to_pages(task.description):
        context.links.note_body(SearchEntityType.task, task.id)
    # An exported description names other things by the refs they had; they
    # are placed once every entry of the job has been written.
    task.description = note_or_settle(
        context, SearchEntityType.task, task.id, task.description
    )

    # What this task was called at the source, and what it says it points at.
    # Both are handed to the job's collector and resolved once every entry has
    # been applied — see ``import_engine.links``.
    if context is not None:
        context.links.register(
            envelope_task.external_ref, SearchEntityType.task, task.id
        )
        for link in envelope_task.links:
            context.links.link(
                envelope_task.external_ref, link.type, link.target_external_ref
            )

    # A reply hangs under the comment it answers. The envelope lists comments
    # oldest first, so a parent is written before its replies; only a comment
    # something answers is flushed for its id. A reply whose parent did not
    # come across (restricted at the source, or empty) stands on its own.
    answered = {
        c.reply_to_ref for c in envelope_task.comments if c.reply_to_ref is not None
    }
    written: dict[str, int] = {}
    comment_count = 0
    for envelope_comment in envelope_task.comments:
        body = (envelope_comment.body or "").strip()
        if not body:
            continue
        author_id, source_name = _comment_author(
            envelope_comment,
            context=context,
            initiative_member_handles=initiative_member_handles,
            importer_id=importer_id,
        )
        comment = Comment(
            task_id=task.id,
            content=_link_mentions(
                body,
                envelope_comment.mention_handles,
                context=context,
                initiative_member_handles=initiative_member_handles,
            ),
            created_by=author_id,
            imported_author_name=source_name,
            parent_comment_id=written.get(envelope_comment.reply_to_ref or ""),
            created_at=envelope_comment.created_at or datetime.now(timezone.utc),
        )
        session.add(comment)
        if context is not None and links_to_pages(comment.content):
            await session.flush()
            context.links.note_body(SearchEntityType.comment, comment.id)
        if has_source_references(comment.content):
            await session.flush()
            comment.content = note_or_settle(
                context, SearchEntityType.comment, comment.id, comment.content
            )
        ref = envelope_comment.external_ref
        if ref is not None and ref in answered and ref not in written:
            await session.flush()
            written[ref] = comment.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        comment_count += 1

    return len(seen_user_ids), comment_count


def _timestamps(envelope_task: ProjectExportTask) -> dict[str, datetime]:
    """The creation/update times to write, if the envelope carried any.

    Returned as kwargs rather than values so an absent field falls through to
    the model's own default instead of overwriting it with None.
    """
    stamps: dict[str, datetime] = {}
    if envelope_task.created_at is not None:
        stamps["created_at"] = envelope_task.created_at
    if envelope_task.updated_at is not None:
        stamps["updated_at"] = envelope_task.updated_at
    return stamps


def _link_mentions(
    text: str | None,
    handles: list[str],
    *,
    context: ImportContext | None,
    initiative_member_handles: dict[str, int],
) -> str | None:
    """``text`` with each ``@<handle>`` it mentions linked to an account here.

    Placed the way a comment's author is (:func:`_comment_author`): the
    account the people step mapped the handle to, else a member of the target
    initiative with that exact handle. A mention nobody places stays the name
    it arrived as. Handles are tried longest first, so ``@Ann Lee`` is never
    read as ``@Ann`` followed by a surname.
    """
    if not text or not handles:
        return text
    people = context.people if context is not None else PeopleMap()
    targets: dict[str, int] = {}
    for handle in handles:
        mapped = quoted_account(
            handle, people=people, member_handles=initiative_member_handles
        )
        if mapped is not None:
            targets[handle] = mapped
    if not targets:
        return text
    ordered = sorted(set(handles), key=len, reverse=True)
    pattern = re.compile("@(" + "|".join(re.escape(h) for h in ordered) + r")(?![\w])")

    def link(match: re.Match[str]) -> str:
        handle = match.group(1)
        user_id = targets.get(handle)
        if user_id is None:
            return match.group(0)
        label = handle.replace("[", "").replace("]", "")
        return f"@[{label}]({user_id})"

    return pattern.sub(link, text)


def _comment_author(
    envelope_comment: ProjectExportComment,
    *,
    context: ImportContext | None,
    initiative_member_handles: dict[str, int],
    importer_id: int,
) -> tuple[int, str | None]:
    """Who this comment belongs to here, and whose name to show if nobody.

    Three answers, in the order they are worth anything:

    1. **The account a person mapped this handle to**, in the import wizard's
       people step. This is the only thing that moves authorship, and it moves
       it because somebody read the name and said who it was.
    2. **A member of the target initiative whose handle is the same string.**
       Exact only, and only inside the initiative the comment is landing in —
       a handle is one identifier, and a restore into the community it came
       from is the case this covers.
    3. **Nobody.** The row names the import that wrote it, because every
       guild-content row names what wrote it, and the source's own answer
       rides beside it as ``imported_author_name`` — a name, not an account,
       so the comment shows no avatar and links to no profile.

    What is deliberately missing is a fourth: a near match. A display name
    that looks similar is how one person's words end up under another
    person's face, and telling those two apart is the whole reason the
    wizard asks.
    """
    handle = envelope_comment.author_handle
    mapped = context.people.user_id(handle) if context is not None else None
    if mapped is not None:
        return mapped, None
    if handle:
        member = initiative_member_handles.get(handle_key(handle))
        if member is not None:
            return member, None
    source_name = (
        envelope_comment.author_name or envelope_comment.author_handle or ""
    ).strip()
    return importer_id, source_name[:200] or None
