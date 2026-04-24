"""
Test data factories for creating database models.

This module provides factory functions for creating test instances of database models
with sensible defaults. Each factory function can accept overrides for any field.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import create_access_token, get_password_hash
from app.models.calendar_event import CalendarEvent
from app.models.document import Document
from app.models.guild import Guild, GuildMembership, GuildRole
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project, ProjectPermission, ProjectPermissionLevel
from app.models.property import (
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.queue import Queue, QueueItem
from app.models.task import Task
from app.models.user import User, UserRole
from app.services.initiatives import create_builtin_roles


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
    email_raw = overrides.pop("email", f"user-{datetime.now(timezone.utc).timestamp()}@example.com").lower().strip()
    defaults = {
        "email_hash": hash_email(email_raw),
        "email_encrypted": encrypt_field(email_raw, SALT_EMAIL),
        "full_name": "Test User",
        "hashed_password": get_password_hash("testpassword123"),
        "role": UserRole.member,
        "is_active": True,
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


def get_guild_headers(guild: Guild, user: User | None = None) -> dict[str, str]:
    """
    Get headers for guild-scoped API requests.

    Args:
        guild: Guild context for the request
        user: Optional user to authenticate as

    Returns:
        Dictionary with X-Guild-ID header (and Authorization if user provided)

    Example:
        headers = get_guild_headers(test_guild, test_user)
        response = await client.get("/api/v1/initiatives", headers=headers)
    """
    headers = {"X-Guild-ID": str(guild.id)}
    if user:
        headers.update(get_auth_headers(user))
    return headers


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
    defaults = {
        "name": f"Test Initiative {datetime.now(timezone.utc).timestamp()}",
        "description": "A test initiative",
        "guild_id": guild.id,
        "queues_enabled": True,
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

        # Create owner permission so the project is visible via DAC
        owner_permission = ProjectPermission(
            project_id=project.id,
            user_id=owner.id,
            level=ProjectPermissionLevel.owner,
            guild_id=project.guild_id,
        )
        session.add(owner_permission)
        await session.commit()

    return project


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
    from app.models.queue import QueuePermission, QueuePermissionLevel

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

        # Create owner permission for creator
        owner_perm = QueuePermission(
            queue_id=queue.id,
            user_id=creator.id,
            guild_id=queue.guild_id,
            level=QueuePermissionLevel.owner,
        )
        session.add(owner_perm)
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
    from app.models.initiative import InitiativeRoleModel
    from sqlmodel import select

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
    row = CalendarEventPropertyValue(
        event_id=event.id,
        property_id=definition.id,
        **value_kwargs,
    )
    session.add(row)

    if commit:
        await session.commit()

    return row
