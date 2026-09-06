"""The recent-views trigger knows every tool.

``public.fn_recent_views_set_guild_id`` denormalizes ``guild_id`` from whatever
a recent view points at, through a plpgsql ``CASE`` with one arm per recentable
type. A plpgsql ``CASE`` with no matching branch *raises* — unlike a SQL one,
which is simply NULL — so a tool with no arm makes opening it a 500.

That is exactly what shipped with posts: the migration added ``'post'`` to the
``ck_recent_views_entity_type`` allow-list and not to this function, and the two
lists drifted with nothing to notice. These are what notice.
"""

import re

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import RECENTABLE_TOOLS
from app.schemas.tenant.recent_view import RecentEntityType
from app.services.tenant import recent_views as recent_views_service
from app.testing import route_session_to_guild
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_post,
    create_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.service]

_ARM = re.compile(r"WHEN '(\w+)'")


async def _function_source(session: AsyncSession) -> str:
    await session.exec(text("SET search_path TO public"))
    return (
        await session.exec(
            text(
                "SELECT prosrc FROM pg_proc "
                "WHERE proname = 'fn_recent_views_set_guild_id'"
            )
        )
    ).scalar_one()


async def test_the_trigger_has_an_arm_for_every_recentable_tool(session: AsyncSession):
    source = await _function_source(session)
    arms = set(_ARM.findall(source))
    expected = {tool.value for tool in RECENTABLE_TOOLS}
    assert arms == expected, (
        "fn_recent_views_set_guild_id drifted from the Tool registry: missing "
        f"{sorted(expected - arms)}, unexpected {sorted(arms - expected)}. A "
        "recentable type with no arm makes every view of it fail."
    )


async def test_the_trigger_names_a_type_it_cannot_place(session: AsyncSession):
    """The ELSE. A type with no arm is a bug either way; this makes the error
    say which type, rather than 'CASE statement is missing ELSE part'."""
    source = await _function_source(session)
    assert "ELSE" in source
    assert "RAISE EXCEPTION" in source


async def test_viewing_a_post_records_it(session: AsyncSession):
    """The end-to-end shape of the bug: the insert itself, through the trigger
    and the policies, for the tool that was missing its arm."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    post = await create_post(session, initiative, user)

    await route_session_to_guild(session, guild.id)
    record = await recent_views_service.record_view(
        session,
        user_id=user.id,
        entity_type=RecentEntityType.post,
        entity_id=post.id,
    )
    await session.commit()

    assert record is not None
