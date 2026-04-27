"""Unit tests for the generic soft-delete service.

Covers cascade-stamp on parent deletion, dedup-by-deleted_at on restore,
the needs-reassignment branch, and the upload-preservation invariants for
file-type and native documents.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.soft_delete_filter import select_including_deleted
from app.models.document import Document, DocumentType
from app.models.project import Project
from app.models.task import Task
from app.models.upload import Upload
from app.services.soft_delete import (
    restore_entity,
    soft_delete_entity,
)
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
)


pytestmark = pytest.mark.integration


async def _create_task(session: AsyncSession, project: Project, *, title: str = "T") -> Task:
    """Build a task with a fresh status. The project factory does not seed
    task statuses, so we create one on first use per-project."""
    from sqlmodel import select

    from app.models.task import TaskPriority, TaskStatus, TaskStatusCategory

    status = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == project.id).limit(1)
        )
    ).first()
    if status is None:
        status = TaskStatus(
            guild_id=project.guild_id,
            project_id=project.id,
            name="Todo",
            category=TaskStatusCategory.todo,
            position=0,
            is_default=True,
        )
        session.add(status)
        await session.commit()
        await session.refresh(status)
    task = Task(
        guild_id=project.guild_id,
        project_id=project.id,
        task_status_id=status.id,
        title=title,
        priority=TaskPriority.medium,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Cascade stamp / unstamp
# ---------------------------------------------------------------------------


async def test_soft_delete_project_cascades_to_tasks(session: AsyncSession):
    """Soft-deleting a project stamps the same deleted_at on every task,
    so children are hidden behind the parent in default selects."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    task_a = await _create_task(session, project, title="A")
    task_b = await _create_task(session, project, title="B")

    await soft_delete_entity(
        session, project, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    refreshed_project = (
        await session.exec(
            select_including_deleted(Project).where(Project.id == project.id)
        )
    ).one()
    refreshed_a = (
        await session.exec(select_including_deleted(Task).where(Task.id == task_a.id))
    ).one()
    refreshed_b = (
        await session.exec(select_including_deleted(Task).where(Task.id == task_b.id))
    ).one()

    assert refreshed_project.deleted_at is not None
    assert refreshed_a.deleted_at == refreshed_project.deleted_at
    assert refreshed_b.deleted_at == refreshed_project.deleted_at
    assert refreshed_a.deleted_by == user.id
    assert refreshed_a.purge_at is not None


async def test_restore_project_unstamps_only_matching_descendants(
    session: AsyncSession,
):
    """If a task was independently soft-deleted earlier, restoring its
    project must NOT bring that task back — it has its own deleted_at and
    belongs in the trash on its own."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    independently_trashed = await _create_task(session, project, title="indep")
    cascaded = await _create_task(session, project, title="cascaded")

    # 1. Trash the first task on its own.
    await soft_delete_entity(
        session, independently_trashed, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    # 2. Trash the project — this stamps `cascaded` but leaves the
    #    already-trashed task's deleted_at intact (different timestamp).
    await soft_delete_entity(
        session, project, deleted_by_user_id=user.id, retention_days=30
    )
    await session.commit()

    # 3. Restore the project.
    result = await restore_entity(session, project)
    assert not result.needs_reassignment
    await session.commit()

    refreshed_indep = (
        await session.exec(
            select_including_deleted(Task).where(Task.id == independently_trashed.id)
        )
    ).one()
    refreshed_cascaded = (
        await session.exec(
            select_including_deleted(Task).where(Task.id == cascaded.id)
        )
    ).one()

    assert refreshed_indep.deleted_at is not None  # still trashed
    assert refreshed_cascaded.deleted_at is None  # restored


# ---------------------------------------------------------------------------
# Restore needs-reassignment
# ---------------------------------------------------------------------------


async def test_restore_returns_needs_reassignment_when_owner_left_initiative(
    session: AsyncSession,
):
    """When the owner of a trashed task is no longer an active initiative
    member, restore must refuse and return the candidate-owner list rather
    than restoring under a stale owner."""
    pm = await create_user(session, email="pm@example.com")
    departed = await create_user(session, email="departed@example.com")
    guild = await create_guild(session, creator=pm)
    initiative = await create_initiative(session, guild, pm)
    await create_initiative_member(session, initiative=initiative, user=departed)
    project = await create_project(session, initiative, departed)
    task = await _create_task(session, project, title="Owner-checked")

    await soft_delete_entity(
        session, task, deleted_by_user_id=departed.id, retention_days=30
    )
    await session.commit()

    # Simulate "owner left the initiative": delete the membership row.
    from sqlmodel import select

    from app.models.initiative import InitiativeMember

    membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == departed.id,
            )
        )
    ).one()
    await session.delete(membership)
    await session.commit()

    result = await restore_entity(session, task)

    assert result.needs_reassignment is True
    assert result.valid_owner_ids == [pm.id]

    # Resubmit with the valid owner.
    refreshed_task = (
        await session.exec(select_including_deleted(Task).where(Task.id == task.id))
    ).one()
    result2 = await restore_entity(session, refreshed_task, new_owner_id=pm.id)
    await session.commit()
    assert not result2.needs_reassignment
    refreshed_again = (
        await session.exec(select_including_deleted(Task).where(Task.id == task.id))
    ).one()
    assert refreshed_again.deleted_at is None
    assert refreshed_again.created_by_id == pm.id


async def test_restore_rejects_invalid_new_owner(session: AsyncSession):
    """Passing a new_owner_id that isn't an active initiative member is a
    400 (TRASH_INVALID_OWNER), not a silent reassign-and-restore."""
    pm = await create_user(session)
    bystander = await create_user(session)
    guild = await create_guild(session, creator=pm)
    initiative = await create_initiative(session, guild, pm)
    project = await create_project(session, initiative, pm)

    await soft_delete_entity(
        session, project, deleted_by_user_id=pm.id, retention_days=30
    )
    await session.commit()

    with pytest.raises(ValueError, match="TRASH_INVALID_OWNER"):
        await restore_entity(session, project, new_owner_id=bystander.id)


# ---------------------------------------------------------------------------
# RLS DELETE deny — policy presence
# ---------------------------------------------------------------------------


async def test_restrictive_delete_policy_exists_on_each_soft_delete_table(
    session: AsyncSession,
):
    """The migration creates a RESTRICTIVE FOR DELETE policy on every
    soft-delete-capable table that admits only sessions where
    ``app.current_guild_role`` is ``admin`` (or superadmin). The test
    fixture connects via the BYPASSRLS admin role so it can't exercise
    the policy at runtime — verify by inspecting pg_policies instead."""
    expected = {
        "projects",
        "tasks",
        "documents",
        "comments",
        "initiatives",
        "tags",
        "queues",
        "queue_items",
        "calendar_events",
    }
    result = await session.execute(text(
        "SELECT tablename, policyname, cmd, permissive "
        "FROM pg_policies "
        "WHERE policyname LIKE '%_delete_admin_only'"
    ))
    rows = result.all()
    found_tables = {row[0] for row in rows}
    assert expected.issubset(found_tables), f"missing on: {expected - found_tables}"
    for tname, pname, cmd, permissive in rows:
        if tname in expected:
            assert cmd == "DELETE", f"{tname}: {pname} cmd={cmd}"
            assert permissive == "RESTRICTIVE", f"{tname}: {pname} permissive={permissive}"


# ---------------------------------------------------------------------------
# Upload preservation
# ---------------------------------------------------------------------------


async def test_soft_delete_document_preserves_uploads(session: AsyncSession):
    """Soft-deleting a native document leaves its referenced Upload row
    alone so the image still works after a restore."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    upload = Upload(
        filename="abc123.png",
        guild_id=guild.id,
        uploader_user_id=user.id,
        size_bytes=1234,
    )
    session.add(upload)
    await session.commit()

    doc = Document(
        guild_id=guild.id,
        initiative_id=initiative.id,
        title="With image",
        document_type=DocumentType.native,
        content={"text": "uses /uploads/abc123.png"},
        featured_image_url="/uploads/abc123.png",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    await soft_delete_entity(session, doc, deleted_by_user_id=user.id, retention_days=30)
    await session.commit()

    # Upload row + filename still present after soft-delete.
    from sqlmodel import select

    upload_row = (
        await session.exec(select(Upload).where(Upload.filename == "abc123.png"))
    ).one_or_none()
    assert upload_row is not None


async def test_purge_document_uploads_escapes_like_wildcards(session: AsyncSession):
    """Filenames legitimately contain '_' (a LIKE metacharacter that means
    'any single character'). The orphan check must escape it before
    interpolating into the LIKE pattern, otherwise a doomed document
    referencing /uploads/file_v2.png could appear pinned by an unrelated
    document referencing /uploads/fileXv2.png — and we'd skip cleanup.

    Regression: the previous implementation interpolated the URL directly
    into the pattern without escaping, leaking blobs on disk."""
    from sqlmodel import select

    from app.services.attachments import purge_document_uploads

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    upload = Upload(
        filename="file_v2.png",
        guild_id=guild.id,
        uploader_user_id=user.id,
        size_bytes=1234,
    )
    session.add(upload)
    await session.commit()

    # The doomed doc references /uploads/file_v2.png — pinned via
    # featured_image_url so extract_upload_urls picks it up cleanly.
    doomed = Document(
        guild_id=guild.id,
        initiative_id=initiative.id,
        title="Doomed",
        document_type=DocumentType.native,
        content={},
        featured_image_url="/uploads/file_v2.png",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    # The decoy uses /uploads/fileXv2.png embedded in content. Without
    # escaping, the LIKE pattern '%/uploads/file_v2.png%' matches the
    # decoy's content (since '_' is "any single char"), and the doomed
    # doc's URL appears pinned by an unrelated document.
    decoy = Document(
        guild_id=guild.id,
        initiative_id=initiative.id,
        title="Decoy",
        document_type=DocumentType.native,
        content={"src": "/uploads/fileXv2.png"},
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    session.add(doomed)
    session.add(decoy)
    await session.commit()
    await session.refresh(doomed)

    await purge_document_uploads(session, [doomed])
    await session.commit()

    # The Upload row backing /uploads/file_v2.png had no other reference,
    # so it should be gone. With the bug, the decoy's URL would have
    # matched and the Upload would have been left behind.
    remaining = (
        await session.exec(select(Upload).where(Upload.filename == "file_v2.png"))
    ).one_or_none()
    assert remaining is None
