"""Unit tests: SQL-identifier builders reject hostile input (Tier 3).

The tenancy model leans on one property — a request can never cause an
attacker-chosen string to become a Postgres role/schema name. Two mechanisms
enforce it: guild identifiers are coerced with ``int()`` inside every name
builder, and the two string-valued role inputs (guild role, platform tier) are
allow-listed in :func:`set_rls_context` before they reach the ``SET ROLE`` sink.
These tests pin both so a regression can't quietly reopen the sink.
"""

from __future__ import annotations

import re

import pytest

from app.db.schema_provisioning import (
    PLATFORM_TIERS,
    guild_readonly_role_name,
    guild_role_name,
    guild_schema_name,
    guild_support_role_name,
    platform_role_name,
)
from app.db.session import set_rls_context

pytestmark = pytest.mark.unit

_GUILD_ID_BUILDERS = (
    guild_schema_name,
    guild_role_name,
    guild_readonly_role_name,
    guild_support_role_name,
)

# Values a path/query param could smuggle if int-coercion were ever dropped.
_HOSTILE_GUILD_IDS = [
    "3; DROP ROLE app_admin",
    "1 OR 1=1",
    "1'; --",
    "42) ; SELECT",
    "guild_1",
    "",
    "  ",
    None,
    3.5,
]


@pytest.mark.parametrize("builder", _GUILD_ID_BUILDERS, ids=lambda b: b.__name__)
@pytest.mark.parametrize("hostile", _HOSTILE_GUILD_IDS, ids=repr)
def test_guild_name_builders_reject_or_sanitize_hostile_ids(builder, hostile):
    """A guild-name builder must never emit an injectable identifier from a
    non-integer id — it either raises (``int()`` on a string/None) or coerces
    to a digits-only name (a truncating float can't smuggle characters)."""
    try:
        name = builder(hostile)
    except (ValueError, TypeError):
        return  # rejected outright — the common case
    assert re.fullmatch(r"[A-Za-z0-9_]*guild_[0-9]+(_ro|_support)?", name), name


@pytest.mark.parametrize("builder", _GUILD_ID_BUILDERS, ids=lambda b: b.__name__)
def test_guild_name_builders_emit_identifier_safe_names(builder):
    """For a real integer id the output is only ``<prefix>guild_<digits>`` with
    an optional ``_ro``/``_support`` suffix — no quotable characters."""
    name = builder(42)
    assert re.fullmatch(r"[A-Za-z0-9_]*guild_42(_ro|_support)?", name), name


@pytest.mark.parametrize("tier", PLATFORM_TIERS)
def test_platform_role_name_is_identifier_safe_for_valid_tiers(tier):
    name = platform_role_name(tier)
    assert re.fullmatch(rf"[A-Za-z0-9_]*platform_{tier}", name), name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_platform_role",
    ["owner'; DROP ROLE app_admin; --", "superuser", "member ", "", "ADMIN"],
)
async def test_set_rls_context_rejects_unknown_platform_tier(hostile_platform_role):
    """The platform tier is allow-listed against the known ladder before it can
    reach the ``SET ROLE`` name sink — validation happens before the session is
    touched, so a bad value fails closed."""
    with pytest.raises(ValueError):
        await set_rls_context(None, platform_role=hostile_platform_role)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_guild_role",
    ["admin'; --", "owner", "superuser", "Admin", "member x"],
)
async def test_set_rls_context_rejects_unknown_guild_role(hostile_guild_role):
    """The guild role GUC is restricted to {'admin', 'member'} before use."""
    with pytest.raises(ValueError):
        await set_rls_context(None, guild_role=hostile_guild_role)
