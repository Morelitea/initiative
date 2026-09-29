"""Fill a database with one community's worth of content, using the checkout's
own test factories.

Run from the ``backend/`` directory of *any* release checkout, with that
release's environment: ``python <path>/upgrade_seed.py``. Every name it imports
is resolved in that release, so the rows are the ones that release writes —
which is what an upgrade from it has to carry. It is kept to the factories
every supported release has; ``upgrade_from_release.py`` runs it against the
release an upgrade starts from, and against the current tree.

The connection is the database owner (``DATABASE_URL_BOOTSTRAP``), as the test
suite's is: the factories write shared and guild tables directly, the way
fixtures do, rather than through a request.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from app.models.platform.guild import GuildRole  # noqa: E402
from app.testing import (  # noqa: E402
    TOOL_FACTORIES,
    checklist_items,
    create_calendar_event,
    create_comment,
    create_counter,
    create_document,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_property_definition,
    create_queue_item,
    create_reaction,
    create_tag,
    create_task,
    create_task_property_value,
    create_upload,
    create_user,
    create_wiki_page,
    enable_all_tools,
)
from app.testing.schema_harness import install_guild_routing  # noqa: E402


async def seed(session: AsyncSession) -> None:
    owner = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=member, guild=guild)
    await create_guild_membership(
        session, user=await create_user(session), guild=guild, role=GuildRole.admin
    )

    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, member)
    initiative = await enable_all_tools(session, initiative)

    # One of every tool, from the registry, so a tool added later is seeded
    # without an edit here.
    tools = {
        tool: await factory(session, initiative, owner)
        for tool, factory in TOOL_FACTORIES.items()
    }
    by_name = {tool.value: entity for tool, entity in tools.items()}

    project = await create_project(session, initiative, owner)
    task = await create_task(
        session,
        project,
        assignees=[member],
        checklist=checklist_items("first", "second"),
    )
    definition = await create_property_definition(session, initiative)
    await create_task_property_value(session, task, definition, value_text="seeded")

    document = await create_document(session, initiative, member)
    comment = await create_comment(session, member, task=task)
    await create_comment(session, owner, document=document)
    await create_reaction(session, owner, comment=comment)

    await create_tag(session, guild)
    await create_upload(session, guild, owner)
    await create_queue_item(session, by_name["queue"])
    await create_counter(session, by_name["counter_group"])
    await create_calendar_event(session, by_name["calendar"], owner)
    await create_wiki_page(session, by_name["wiki"], owner)


async def main() -> None:
    install_guild_routing()
    engine = create_async_engine(os.environ["DATABASE_URL_BOOTSTRAP"])
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
