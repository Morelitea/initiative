"""Why a row the request asked for was not there.

Gate 4 is a policy, so a resource a reader may not reach is simply absent by
the time a handler runs — and "not yours" and "not there" are different
answers. This asks the system engine that one question and takes back a yes or
no, never a row.

It is a *status-code* decision, not a gate: nothing here grants access, and
every caller has already been refused by the database before it asks.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import SQLModel, select

from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole


def _model_for(table: str) -> Optional[type[SQLModel]]:
    """The mapped class behind a table name, or None for a table with none."""
    for mapper in SQLModel._sa_registry.mappers:
        if mapper.local_table is not None and mapper.local_table.name == table:
            return mapper.class_
    return None


def _initiative_query(model: Any, row_id: int):
    """A select yielding ``row_id``'s initiative, or nothing if it is not there.

    Most tables carry ``initiative_id``. A task does not — it belongs to a
    project — so it is read through the join its own policies use.
    """
    live = getattr(model, "deleted_at", None)
    if hasattr(model, "initiative_id"):
        statement = select(model.initiative_id).where(model.id == row_id)
    else:
        from app.models.tenant.project import Project

        statement = (
            select(Project.initiative_id)
            .join(model, model.project_id == Project.id)
            .where(model.id == row_id)
        )
    if live is not None:
        statement = statement.where(live.is_(None))
    return statement


async def reader_is_in_the_initiative(
    table: str, row_id: int, user_id: int, guild_id: int
) -> bool:
    """Whether ``row_id`` belongs to an initiative ``user_id`` is a member of.

    Routed as the guild's own admin, which is how every other system read
    reaches guild content. A row belonging to no initiative (a guild calendar)
    has no initiative gate to fail, so reaching this point means a later gate
    refused it.
    """
    from app.models.tenant.initiative import InitiativeMember

    model = _model_for(table)
    if model is None:
        return False

    # Late-bound (module attribute at call time) so the test harness's
    # sessionmaker patch applies to the probe too.
    async with db_session.AdminSessionLocal() as probe, probe.begin():
        # One transaction, explicitly: the routing is transaction-local, and the
        # probe runs on a session of its own rather than the request's.
        await set_rls_context(
            probe, guild_id=guild_id, guild_role=GuildRole.admin.value
        )
        found = (await probe.exec(_initiative_query(model, row_id))).first()
        if found is None:
            return False
        initiative_id = found[0] if isinstance(found, tuple) else found
        if initiative_id is None:
            return True
        member = (
            await probe.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative_id,
                    InitiativeMember.user_id == user_id,
                )
            )
        ).first()
    return member is not None
