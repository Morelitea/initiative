"""Shared import conventions — extracted from ``project_import.py`` (the
proven importer) so every per-type importer resolves cross-references the
same way:

* tags match-or-create by ``(guild_id, name)``;
* property definitions match by name+type with option-set compatibility,
  renamed on collision (never mutate the target's definition);
* people resolve by email against the TARGET INITIATIVE's members only,
  with unmatched emails reported, never guessed;
* names de-duplicate with an ``" (imported)"`` suffix.

``project_import.py`` re-imports these — one implementation, two callers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.property import PropertyDefinition, PropertyType
from app.models.tenant.tag import Tag


class TagResolved:
    __slots__ = ("id", "created")

    def __init__(self, *, id: int, created: bool) -> None:
        self.id = id
        self.created = created


_SELECT_TYPES = {PropertyType.select, PropertyType.multi_select}


def options_compatible(
    prop_type: PropertyType,
    target_options: list[dict] | None,
    source_options: list[dict] | None,
) -> bool:
    """Return True when reusing the target's definition is safe.

    For non-select types, options are irrelevant. For select / multi_select,
    the *value* sets must match: stored values reference the option's
    ``value`` field, so a target definition with a different option list
    would silently break filtering and rendering for imported rows. Labels
    are cosmetic and ignored.
    """
    if prop_type not in _SELECT_TYPES:
        return True
    target_values = {
        o.get("value") for o in (target_options or []) if isinstance(o, dict)
    }
    source_values = {
        o.get("value") for o in (source_options or []) if isinstance(o, dict)
    }
    return target_values == source_values


async def ensure_tag(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str,
    color: str,
) -> TagResolved:
    """Find a tag by ``(guild_id, name)`` or create it.

    ``guild_id`` is intentionally non-optional: a ``None`` here would
    silently match guild-less tags (``WHERE guild_id IS NULL``) and
    cross-pollinate across guilds. Callers must guarantee a real guild
    before reaching this helper.
    """
    stmt = select(Tag).where(Tag.guild_id == guild_id, Tag.name == name)
    existing = (await session.exec(stmt)).one_or_none()
    if existing is not None:
        return TagResolved(id=existing.id, created=False)
    tag = Tag(guild_id=guild_id, name=name, color=color)
    session.add(tag)
    await session.flush()
    return TagResolved(id=tag.id, created=True)


def unique_name(existing: set[str], desired: str, *, suffix: str = "imported") -> str:
    """Append ' (imported)' / ' (imported 2)' until the name is free.
    Soft, non-fatal collision handling — the always-create policy."""
    if desired not in existing:
        return desired
    candidate = f"{desired} ({suffix})"
    n = 2
    while candidate in existing:
        candidate = f"{desired} ({suffix} {n})"
        n += 1
    return candidate


async def unique_property_name(
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


async def load_initiative_member_emails(
    session: AsyncSession, *, initiative_id: int
) -> dict[str, int]:
    """Map ``email → user_id`` for the target initiative's members.

    People are matched against members of the *initiative*, not the wider
    guild. ``User.email`` is a decryption property, not a column, so we load
    the User row and read the property in Python rather than projecting the
    column.
    """
    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
    )
    users = (await session.exec(stmt)).all()
    return {user.email: user.id for user in users if user.email}  # ty: ignore[invalid-return-type] — persisted rows, ids are set


async def load_initiative_properties(
    session: AsyncSession, *, initiative_id: int
) -> dict[str, PropertyDefinition]:
    stmt = select(PropertyDefinition).where(
        PropertyDefinition.initiative_id == initiative_id
    )
    return {pd.name: pd for pd in (await session.exec(stmt)).all()}


class ResolvedProperties:
    """Outcome of resolving a batch of property definitions."""

    __slots__ = ("key_to_id", "created", "matched", "renamed")

    def __init__(self) -> None:
        self.key_to_id: dict[tuple[str, PropertyType], int] = {}
        self.created = 0
        self.matched = 0
        self.renamed: list[str] = []


class _EnvelopePropertyDefinition(Protocol):
    name: str
    type: PropertyType
    position: int
    color: str | None
    options: list[dict] | None


async def resolve_property_definitions(
    session: AsyncSession,
    *,
    initiative_id: int,
    definitions: list[Any],
) -> ResolvedProperties:
    """Match-or-create property definitions by name+type. On a name collision
    with a different type or an incompatible option set, create a renamed
    ``<name>_<type>`` definition instead of mutating the target's existing
    one (its stored values would silently break otherwise)."""
    existing = await load_initiative_properties(session, initiative_id=initiative_id)
    resolved = ResolvedProperties()
    for pd in definitions:
        match_existing = existing.get(pd.name)
        if (
            match_existing is not None
            and match_existing.type == pd.type
            and options_compatible(pd.type, match_existing.options, pd.options)
        ):
            resolved.key_to_id[(pd.name, pd.type)] = match_existing.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            resolved.matched += 1
            continue
        target_name = pd.name
        if match_existing is not None:
            target_name = await unique_property_name(
                session,
                initiative_id=initiative_id,
                desired_name=f"{pd.name}_{pd.type.value}",
            )
            resolved.renamed.append(target_name)
        new_def = PropertyDefinition(
            initiative_id=initiative_id,
            name=target_name,
            type=pd.type,
            position=pd.position,
            color=pd.color,
            options=pd.options,
        )
        session.add(new_def)
        await session.flush()
        resolved.key_to_id[(pd.name, pd.type)] = new_def.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        # Track for subsequent collision-renames within this import.
        existing[target_name] = new_def
        resolved.created += 1
    return resolved


class _EnvelopePropertyValue(Protocol):
    property_type: PropertyType
    value_text: str | None
    value_number: float | None
    value_boolean: bool | None
    value_json: Any
    value_email: str | None


def decode_property_value(
    pv: _EnvelopePropertyValue,
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
        return {"value_date": parse_date(pv.value_text)}
    if t == PropertyType.datetime:
        return {"value_datetime": parse_datetime(pv.value_text)}
    if t == PropertyType.multi_select:
        return {"value_json": pv.value_json}
    if t == PropertyType.user_reference:
        if not pv.value_email:
            return {"value_user_id": None}
        uid = initiative_member_emails.get(pv.value_email)
        if uid is None:
            # Drop the value rather than the whole row; the UI renders the
            # property as "—".
            return None
        return {"value_user_id": uid}
    return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
