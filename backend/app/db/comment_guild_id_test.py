"""A comment records which community it is in, whatever it hangs off.

``comments.guild_id`` is denormalized by a trigger rather than written by the
service, and the guild-wide surfaces (the recent-activity feed) filter on it.
So a parent the trigger has no arm for does not fail loudly — the thread still
reads back, and the comment is simply missing from the feed for ever.

That is what went wrong between 0192 and 0317: three tools arrived and none of
them extended the function. These hold the live definitions to the parent
registry so the next one cannot.
"""

import pytest
from sqlalchemy import text

from app.core.tools import Tool
from app.db.initiative_rls import COMMENT_PARENTS
from app.testing import (
    create_comment,
    create_guild,
    create_initiative,
    create_user,
    create_wiki_page,
)
from app.testing.factories import TOOL_FACTORIES
from app.testing.schema_harness import route_session_to_guild

pytestmark = pytest.mark.database


async def test_the_trigger_function_has_an_arm_for_every_parent(session):
    source = (
        await session.exec(
            text(
                "SELECT prosrc FROM pg_proc WHERE proname = 'fn_comments_set_guild_id'"
            )
        )
    ).scalar()
    assert source is not None, "the denormalization function is missing"

    missing = [
        column
        for column, parent in COMMENT_PARENTS.items()
        if f"NEW.{column} IS NOT NULL" not in source
        or f"FROM {parent.table} WHERE id = NEW.{column}" not in source
    ]
    assert not missing, (
        f"{missing} have no arm in fn_comments_set_guild_id, so a comment on "
        "one is written with no guild and never reaches the activity feed."
    )


async def test_the_trigger_fires_on_every_parent_column(session):
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)

    definition = (
        await session.exec(
            text(
                "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE t.tgname = 'tr_comments_set_guild_id' "
                "AND c.relname = 'comments' AND n.nspname = :schema"
            ).bindparams(schema=f"guild_{guild.id}")
        )
    ).scalar()
    assert definition is not None, "the per-schema trigger is missing"

    missing = [column for column in COMMENT_PARENTS if column not in definition]
    assert not missing, f"{missing} are not in the trigger's UPDATE OF list"


@pytest.mark.parametrize("tool", list(Tool))
async def test_a_comment_on_any_tool_records_its_guild(session, tool):
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    entity = await TOOL_FACTORIES[tool](session, initiative, owner)

    comment = await create_comment(session, owner, **{tool.value: entity})
    await route_session_to_guild(session, guild.id)
    await session.refresh(comment)
    assert comment.guild_id == guild.id


async def test_a_comment_on_a_wiki_page_records_its_guild(session):
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    wiki = await TOOL_FACTORIES[Tool.wiki](session, initiative, owner)
    page = await create_wiki_page(session, wiki, owner)

    comment = await create_comment(session, owner, wiki_page=page)
    await route_session_to_guild(session, guild.id)
    await session.refresh(comment)
    assert comment.guild_id == guild.id
