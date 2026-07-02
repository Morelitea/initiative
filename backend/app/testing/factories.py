"""
Test data factories for creating database models.

This module provides factory functions for creating test instances of database
models with sensible defaults. Each factory function can accept overrides for
any field.

Schema-per-guild: tenant models live in per-guild Postgres schemas, never in
``public``. Every tenant factory therefore routes its session to the target
guild's schema (``route_session_to_guild``) before reading or writing, derived
from the parent object it receives — so factory calls are deterministic
regardless of flush composition. Raw ``session.add()`` of tenant models in
tests is covered by the fail-closed flush router in ``schema_harness``.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import create_access_token, get_password_hash
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.comment import Comment
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.document import Document, DocumentType
from app.models.platform.guild import Guild, GuildMembership, GuildRole
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant, ResourceAccessLevel
from app.models.tenant.property import (
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.tag import Tag
from app.models.tenant.task import (
    Subtask,
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.upload import Upload
from app.models.platform.user import User, UserRole, UserStatus
from app.services.tenant.initiatives import create_builtin_roles
from app.testing.schema_harness import route_session_to_guild


async def create_user(
    session: AsyncSession,
    commit: bool = True,
    **overrides: Any,
) -> User:
    """
    Create a test user with sensible defaults.

    Args:
        session: Database session
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created User instance

    Example:
        user = await create_user(
            session,
            email="test@example.com",
            role=UserRole.admin
        )
    """
    email_raw = (
        overrides.pop(
            "email", f"user-{datetime.now(timezone.utc).timestamp()}@example.com"
        )
        .lower()
        .strip()
    )
    defaults = {
        "email_hash": hash_email(email_raw),
        "email_encrypted": encrypt_field(email_raw, SALT_EMAIL),
        "full_name": "Test User",
        "hashed_password": get_password_hash("testpassword123"),
        "role": UserRole.member,
        "status": UserStatus.active,
        "email_verified": True,
        "week_starts_on": 0,
        "timezone": "UTC",
        "overdue_notification_time": "21:00",
        "email_initiative_addition": True,
        "email_task_assignment": True,
        "email_project_added": True,
        "email_overdue_tasks": True,
        "email_mentions": True,
        "push_initiative_addition": True,
        "push_task_assignment": True,
        "push_project_added": True,
        "push_overdue_tasks": True,
        "push_mentions": True,
        "email_events": True,
        "push_events": True,
        "email_event_reminders": True,
        "push_event_reminders": True,
        "event_reminder_minutes_before": 15,
    }

    user_data = {**defaults, **overrides}
    user = User(**user_data)
    session.add(user)

    if commit:
        await session.commit()
        await session.refresh(user)

    return user


async def create_guild(
    session: AsyncSession,
    creator: User | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Guild:
    """
    Create a test guild with sensible defaults.

    Args:
        session: Database session
        creator: User who creates the guild (will be created if not provided)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Guild instance

    Example:
        guild = await create_guild(session, name="Test Guild")
    """
    if creator is None:
        creator = await create_user(session, commit=commit)

    defaults = {
        "name": f"Test Guild {datetime.now(timezone.utc).timestamp()}",
        "description": "A test guild for integration testing",
        "created_by_user_id": creator.id,
    }

    guild_data = {**defaults, **overrides}
    guild = Guild(**guild_data)
    session.add(guild)

    if commit:
        await session.commit()
        await session.refresh(guild)
        # Schema-native: commit the guild row, then provision its schema so the
        # routing harness can send this guild's guild-scoped writes into it.
        from app.db.schema_provisioning import provision_guild

        await provision_guild(guild.id)

    return guild


async def create_guild_membership(
    session: AsyncSession,
    user: User | None = None,
    guild: Guild | None = None,
    role: GuildRole = GuildRole.member,
    commit: bool = True,
    **overrides: Any,
) -> GuildMembership:
    """
    Create a guild membership (linking a user to a guild).

    Args:
        session: Database session
        user: User to add to guild (will be created if not provided)
        guild: Guild to add user to (will be created if not provided)
        role: Guild role for the user (default: member)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created GuildMembership instance

    Example:
        membership = await create_guild_membership(
            session,
            user=test_user,
            guild=test_guild,
            role=GuildRole.admin
        )
    """
    if user is None:
        user = await create_user(session, commit=commit)

    if guild is None:
        guild = await create_guild(session, commit=commit)

    defaults = {
        "user_id": user.id,
        "guild_id": guild.id,
        "role": role,
        "position": 0,
    }

    membership_data = {**defaults, **overrides}
    membership = GuildMembership(**membership_data)
    session.add(membership)

    if commit:
        await session.commit()
        await session.refresh(membership)

    return membership


def get_auth_token(user: User) -> str:
    """
    Generate a valid JWT access token for a user.

    Args:
        user: User to generate token for

    Returns:
        JWT access token string

    Example:
        token = get_auth_token(test_user)
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/users/me", headers=headers)
    """
    return create_access_token(subject=str(user.id), token_version=user.token_version)


def get_auth_headers(user: User) -> dict[str, str]:
    """
    Get authorization headers for API requests.

    Args:
        user: User to authenticate as

    Returns:
        Dictionary with Authorization header

    Example:
        headers = get_auth_headers(test_user)
        response = await client.get("/api/v1/users/me", headers=headers)
    """
    token = get_auth_token(user)
    return {"Authorization": f"Bearer {token}"}


async def create_initiative(
    session: AsyncSession,
    guild: Guild,
    creator: User,
    commit: bool = True,
    **overrides: Any,
) -> Initiative:
    """
    Create a test initiative with sensible defaults.

    Args:
        session: Database session
        guild: Guild the initiative belongs to
        creator: User who creates the initiative (will become project manager)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Initiative instance

    Example:
        initiative = await create_initiative(session, guild, user, name="Test Initiative")
    """
    await route_session_to_guild(session, guild.id)

    defaults = {
        "name": f"Test Initiative {datetime.now(timezone.utc).timestamp()}",
        "description": "A test initiative",
        "guild_id": guild.id,
        "queues_enabled": True,
        "counters_enabled": True,
    }

    initiative_data = {**defaults, **overrides}
    initiative = Initiative(**initiative_data)
    session.add(initiative)

    if commit:
        await session.flush()

        # Create built-in roles (PM + Member)
        pm_role, _member_role = await create_builtin_roles(
            session, initiative_id=initiative.id
        )

        # Add creator as project manager with proper role_id
        membership = InitiativeMember(
            initiative_id=initiative.id,
            user_id=creator.id,
            role_id=pm_role.id,
            guild_id=initiative.guild_id,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(initiative)

    return initiative


async def create_project(
    session: AsyncSession,
    initiative: Initiative,
    owner: User,
    commit: bool = True,
    **overrides: Any,
) -> Project:
    """
    Create a test project with sensible defaults.

    Args:
        session: Database session
        initiative: Initiative the project belongs to
        owner: User who owns the project
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Project instance

    Example:
        project = await create_project(session, initiative, user, name="Test Project")
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "name": f"Test Project {datetime.now(timezone.utc).timestamp()}",
        "description": "A test project",
        "initiative_id": initiative.id,
        "owner_id": owner.id,
        "guild_id": initiative.guild_id,
    }

    project_data = {**defaults, **overrides}
    project = Project(**project_data)
    session.add(project)

    if commit:
        await session.commit()
        await session.refresh(project)

        # Owner grant so the project is visible via DAC.
        session.add(
            ResourceGrant(
                resource_type="project",
                resource_id=project.id,
                user_id=owner.id,
                level=ResourceAccessLevel.owner,
                guild_id=project.guild_id,
                initiative_id=project.initiative_id,
            )
        )
        await session.commit()

    return project


async def create_task(
    session: AsyncSession,
    project: Project,
    *,
    title: str | None = None,
    status_category: TaskStatusCategory = TaskStatusCategory.todo,
    assignees: list[User] | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Task:
    """Create a test task (guild-scoped), with a status of the requested
    category and optional assignees.

    Reuses an existing project status of the same category if one exists,
    otherwise creates one. Pass ``status_category=TaskStatusCategory.done`` and
    ``assignees=[user]`` to build a completed, assigned task (e.g. for stats).
    """
    from sqlmodel import select as _select

    await route_session_to_guild(session, project.guild_id)

    status = (
        await session.exec(
            _select(TaskStatus)
            .where(
                TaskStatus.project_id == project.id,
                TaskStatus.category == status_category,
            )
            .limit(1)
        )
    ).first()
    if status is None:
        status = TaskStatus(
            guild_id=project.guild_id,
            project_id=project.id,
            name=status_category.value.replace("_", " ").title(),
            category=status_category,
            position=0,
            is_default=status_category == TaskStatusCategory.todo,
        )
        session.add(status)
        await session.flush()

    defaults: dict[str, Any] = {
        "title": title or f"Test Task {datetime.now(timezone.utc).timestamp()}",
        "project_id": project.id,
        "guild_id": project.guild_id,
        "task_status_id": status.id,
        "priority": TaskPriority.medium,
    }
    task = Task(**{**defaults, **overrides})
    session.add(task)
    if commit:
        await session.commit()
        await session.refresh(task)

    for user in assignees or []:
        session.add(
            TaskAssignee(task_id=task.id, user_id=user.id, guild_id=project.guild_id)
        )
    if commit and assignees:
        await session.commit()

    return task


async def create_queue(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    commit: bool = True,
    **overrides: Any,
) -> Queue:
    """
    Create a test queue with sensible defaults.

    Args:
        session: Database session
        initiative: Initiative the queue belongs to
        creator: User who creates the queue
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created Queue instance
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "name": f"Test Queue {datetime.now(timezone.utc).timestamp()}",
        "description": "A test queue",
        "initiative_id": initiative.id,
        "guild_id": initiative.guild_id,
        "created_by_id": creator.id,
    }

    queue_data = {**defaults, **overrides}
    queue = Queue(**queue_data)
    session.add(queue)

    if commit:
        await session.commit()
        await session.refresh(queue)

        # Owner grant for creator.
        session.add(
            ResourceGrant(
                resource_type="queue",
                resource_id=queue.id,
                user_id=creator.id,
                guild_id=queue.guild_id,
                initiative_id=queue.initiative_id,
                level=ResourceAccessLevel.owner,
            )
        )
        await session.commit()

    return queue


async def create_queue_item(
    session: AsyncSession,
    queue: Queue,
    commit: bool = True,
    **overrides: Any,
) -> QueueItem:
    """
    Create a test queue item with sensible defaults.

    Args:
        session: Database session
        queue: Queue the item belongs to
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created QueueItem instance
    """
    await route_session_to_guild(session, queue.guild_id)

    defaults = {
        "queue_id": queue.id,
        "guild_id": queue.guild_id,
        "label": f"Item {datetime.now(timezone.utc).timestamp()}",
        "position": 0,
        "is_visible": True,
    }

    item_data = {**defaults, **overrides}
    item = QueueItem(**item_data)
    session.add(item)

    if commit:
        await session.commit()
        await session.refresh(item)

    return item


async def create_initiative_member(
    session: AsyncSession,
    initiative: Initiative,
    user: User,
    role_name: str = "member",
    commit: bool = True,
) -> InitiativeMember:
    """
    Create an initiative member with proper role_id.

    Args:
        session: Database session
        initiative: Initiative to add user to
        user: User to add
        role_name: Role name ("project_manager" or "member")
        commit: Whether to commit the transaction

    Returns:
        Created InitiativeMember instance
    """
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    await route_session_to_guild(session, initiative.guild_id)

    # Find the matching role for this initiative
    stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative.id,
        InitiativeRoleModel.name == role_name,
    )
    result = await session.exec(stmt)
    role = result.one_or_none()
    if role is None:
        raise ValueError(
            f"Role '{role_name}' not found for initiative {initiative.id}. "
            "Ensure builtin roles exist (use create_initiative factory)."
        )

    membership = InitiativeMember(
        initiative_id=initiative.id,
        user_id=user.id,
        role_id=role.id,
        guild_id=initiative.guild_id,
    )
    session.add(membership)

    if commit:
        await session.commit()

    return membership


async def create_property_definition(
    session: AsyncSession,
    initiative: Initiative,
    *,
    name: str | None = None,
    type: PropertyType = PropertyType.text,
    options: list[dict] | None = None,
    color: str | None = None,
    position: float = 0.0,
    commit: bool = True,
    **overrides: Any,
) -> PropertyDefinition:
    """
    Create a test property definition with sensible defaults.

    Auto-generates a unique name if not provided. When ``type`` is a
    select/multi_select and ``options`` is None, seeds a default option
    list so the definition is valid.

    Args:
        session: Database session
        initiative: Initiative the definition belongs to
        name: Property name (auto-generated if None)
        type: Property type (default: text)
        options: Option list for select/multi_select types
        color: Optional hex color
        position: Sort position (default: 0.0)
        commit: Whether to commit the transaction (default True)
        **overrides: Override any default field values

    Returns:
        Created PropertyDefinition instance
    """
    await route_session_to_guild(session, initiative.guild_id)

    if name is None:
        name = f"Prop {datetime.now(timezone.utc).timestamp()}"

    if type in {PropertyType.select, PropertyType.multi_select} and options is None:
        options = [
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ]
    elif type not in {PropertyType.select, PropertyType.multi_select}:
        # Non-select types don't store options.
        options = None

    defaults = {
        "initiative_id": initiative.id,
        "name": name,
        "type": type,
        "position": position,
        "color": color,
        "options": options,
    }

    data = {**defaults, **overrides}
    definition = PropertyDefinition(**data)
    session.add(definition)

    if commit:
        await session.commit()
        await session.refresh(definition)

    return definition


async def create_document_property_value(
    session: AsyncSession,
    document: Document,
    definition: PropertyDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> DocumentPropertyValue:
    """
    Attach a typed property value to a document.

    Accepts any of ``value_text``, ``value_number``, ``value_boolean``,
    ``value_date``, ``value_datetime``, ``value_user_id``, ``value_json``.

    Args:
        session: Database session
        document: Document to attach the value to
        definition: PropertyDefinition the value references
        commit: Whether to commit the transaction (default True)
        **value_kwargs: Typed column values

    Returns:
        Created DocumentPropertyValue instance
    """
    await route_session_to_guild(session, document.guild_id)

    row = DocumentPropertyValue(
        document_id=document.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_task_property_value(
    session: AsyncSession,
    task: Task,
    definition: PropertyDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> TaskPropertyValue:
    """
    Attach a typed property value to a task.

    Accepts any of ``value_text``, ``value_number``, ``value_boolean``,
    ``value_date``, ``value_datetime``, ``value_user_id``, ``value_json``.

    Args:
        session: Database session
        task: Task to attach the value to
        definition: PropertyDefinition the value references
        commit: Whether to commit the transaction (default True)
        **value_kwargs: Typed column values

    Returns:
        Created TaskPropertyValue instance
    """
    await route_session_to_guild(session, task.guild_id)

    row = TaskPropertyValue(
        task_id=task.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_calendar_event(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    title: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> CalendarEvent:
    """Create a test calendar event with sensible defaults.

    Defaults to a one-hour event starting "now"; callers that care about
    the timing should override ``start_at`` / ``end_at``. The initiative
    is expected to be events-enabled — callers that need to test the
    feature flag should toggle that on the passed-in ``initiative``.
    """
    await route_session_to_guild(session, initiative.guild_id)

    now = datetime.now(timezone.utc)
    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "created_by_id": creator.id,
        "title": title or f"Event {now.timestamp()}",
        "start_at": now,
        "end_at": now + timedelta(hours=1),
        "all_day": False,
    }

    data = {**defaults, **overrides}
    event = CalendarEvent(**data)
    session.add(event)

    if commit:
        await session.commit()
        await session.refresh(event)

        # Per-event DAC grants, mirroring the create endpoint: creator owns it,
        # each initiative role gets write (managers) or read.
        from app.models.tenant.initiative import InitiativeRoleModel
        from sqlmodel import select

        session.add(
            ResourceGrant(
                resource_type="calendar_event",
                resource_id=event.id,
                user_id=creator.id,
                level=ResourceAccessLevel.owner,
                guild_id=event.guild_id,
                initiative_id=event.initiative_id,
            )
        )
        roles = (
            await session.exec(
                select(InitiativeRoleModel).where(
                    InitiativeRoleModel.initiative_id == initiative.id
                )
            )
        ).all()
        for role in roles:
            session.add(
                ResourceGrant(
                    resource_type="calendar_event",
                    resource_id=event.id,
                    role_id=role.id,
                    level=ResourceAccessLevel.write
                    if role.is_manager
                    else ResourceAccessLevel.read,
                    guild_id=event.guild_id,
                    initiative_id=event.initiative_id,
                )
            )
        await session.commit()

    return event


async def create_calendar_event_property_value(
    session: AsyncSession,
    event: CalendarEvent,
    definition: PropertyDefinition,
    *,
    commit: bool = True,
    **value_kwargs: Any,
) -> CalendarEventPropertyValue:
    """Attach a typed property value to a calendar event.

    Mirrors :func:`create_document_property_value` /
    :func:`create_task_property_value` for the event value table.
    """
    await route_session_to_guild(session, event.guild_id)

    row = CalendarEventPropertyValue(
        event_id=event.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row


async def create_document(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    title: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Document:
    """Create a test document with sensible defaults.

    Defaults to a ``native`` (editor) document with empty content and an
    owner grant for ``creator``, mirroring the create endpoint's DAC setup.
    """
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "title": title or f"Test Document {datetime.now(timezone.utc).timestamp()}",
        "document_type": DocumentType.native,
        "created_by_id": creator.id,
        "updated_by_id": creator.id,
    }
    document = Document(**{**defaults, **overrides})
    session.add(document)

    if commit:
        await session.commit()
        await session.refresh(document)

        session.add(
            ResourceGrant(
                resource_type="document",
                resource_id=document.id,
                user_id=creator.id,
                level=ResourceAccessLevel.owner,
                guild_id=document.guild_id,
                initiative_id=document.initiative_id,
            )
        )
        await session.commit()

    return document


async def create_comment(
    session: AsyncSession,
    author: User,
    *,
    task: Task | None = None,
    document: Document | None = None,
    content: str = "A test comment",
    commit: bool = True,
    **overrides: Any,
) -> Comment:
    """Create a comment on exactly one of ``task`` or ``document``."""
    if (task is None) == (document is None):
        raise ValueError("pass exactly one of task= or document=")
    parent = task if task is not None else document
    await route_session_to_guild(session, parent.guild_id)

    defaults = {
        "guild_id": parent.guild_id,
        "content": content,
        "author_id": author.id,
        "task_id": task.id if task else None,
        "document_id": document.id if document else None,
    }
    comment = Comment(**{**defaults, **overrides})
    session.add(comment)

    if commit:
        await session.commit()
        await session.refresh(comment)

    return comment


async def create_tag(
    session: AsyncSession,
    guild: Guild,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Tag:
    """Create a guild-scoped tag."""
    await route_session_to_guild(session, guild.id)

    defaults = {
        "guild_id": guild.id,
        "name": name or f"tag-{datetime.now(timezone.utc).timestamp()}",
    }
    tag = Tag(**{**defaults, **overrides})
    session.add(tag)

    if commit:
        await session.commit()
        await session.refresh(tag)

    return tag


async def create_subtask(
    session: AsyncSession,
    task: Task,
    *,
    content: str = "A test subtask",
    commit: bool = True,
    **overrides: Any,
) -> Subtask:
    """Create a subtask under ``task``."""
    await route_session_to_guild(session, task.guild_id)

    defaults = {
        "guild_id": task.guild_id,
        "task_id": task.id,
        "content": content,
    }
    subtask = Subtask(**{**defaults, **overrides})
    session.add(subtask)

    if commit:
        await session.commit()
        await session.refresh(subtask)

    return subtask


async def create_task_status(
    session: AsyncSession,
    project: Project,
    *,
    name: str | None = None,
    category: TaskStatusCategory = TaskStatusCategory.todo,
    commit: bool = True,
    **overrides: Any,
) -> TaskStatus:
    """Create a task status for ``project`` (does not deduplicate; use
    ``create_task`` when you just need a task in a given category)."""
    await route_session_to_guild(session, project.guild_id)

    defaults = {
        "guild_id": project.guild_id,
        "project_id": project.id,
        "name": name or category.value.replace("_", " ").title(),
        "category": category,
        "position": 0,
    }
    status = TaskStatus(**{**defaults, **overrides})
    session.add(status)

    if commit:
        await session.commit()
        await session.refresh(status)

    return status


async def create_counter_group(
    session: AsyncSession,
    initiative: Initiative,
    creator: User,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> CounterGroup:
    """Create a counter group with an owner grant for ``creator``."""
    await route_session_to_guild(session, initiative.guild_id)

    defaults = {
        "guild_id": initiative.guild_id,
        "initiative_id": initiative.id,
        "name": name or f"Test Counters {datetime.now(timezone.utc).timestamp()}",
        "created_by_id": creator.id,
    }
    group = CounterGroup(**{**defaults, **overrides})
    session.add(group)

    if commit:
        await session.commit()
        await session.refresh(group)

        session.add(
            ResourceGrant(
                resource_type="counter_group",
                resource_id=group.id,
                user_id=creator.id,
                level=ResourceAccessLevel.owner,
                guild_id=group.guild_id,
                initiative_id=group.initiative_id,
            )
        )
        await session.commit()

    return group


async def create_counter(
    session: AsyncSession,
    group: CounterGroup,
    *,
    name: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Counter:
    """Create a counter inside ``group``."""
    await route_session_to_guild(session, group.guild_id)

    defaults = {
        "guild_id": group.guild_id,
        "counter_group_id": group.id,
        "name": name or f"Counter {datetime.now(timezone.utc).timestamp()}",
    }
    counter = Counter(**{**defaults, **overrides})
    session.add(counter)

    if commit:
        await session.commit()
        await session.refresh(counter)

    return counter


async def create_upload(
    session: AsyncSession,
    guild: Guild,
    uploader: User,
    *,
    filename: str | None = None,
    commit: bool = True,
    **overrides: Any,
) -> Upload:
    """Create an upload row (metadata only; writes no file to disk)."""
    await route_session_to_guild(session, guild.id)

    defaults = {
        "guild_id": guild.id,
        "uploader_user_id": uploader.id,
        "filename": filename or f"file-{datetime.now(timezone.utc).timestamp()}.txt",
        "size_bytes": 1,
    }
    upload = Upload(**{**defaults, **overrides})
    session.add(upload)

    if commit:
        await session.commit()
        await session.refresh(upload)

    return upload
