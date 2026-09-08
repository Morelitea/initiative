"""Why a row the request asked for was not there.

Gate 4 is a policy, so a resource a reader may not reach is simply absent by
the time a handler runs — and "not yours" and "not there" are different
answers. This asks the system engine that one question and takes back a yes or
no, never a row.

It is a *status-code* decision, not a gate: nothing here grants access, and
every caller has already been refused by the database before it asks.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import SQLModel

from app.db.initiative_rls import INITIATIVE_PATHS
from app.db.schema_provisioning import guild_schema_name
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole


async def reader_is_in_the_initiative(
    table: str, row_id: int, user_id: int, guild_id: int
) -> bool:
    """Whether ``row_id`` belongs to an initiative ``user_id`` is a member of.

    How a row of this table finds its initiative comes from ``INITIATIVE_PATHS``
    — the same declaration the table's own policies render from — so a table
    cannot be gated through one initiative and probed through another.

    Routed as the guild's own admin, which is how every other system read
    reaches guild content. A row belonging to no initiative (a guild calendar)
    has no initiative gate to fail, so reaching this point means sharing
    refused it.
    """
    path = INITIATIVE_PATHS.get(table)
    if path is None:
        return False
    initiative = path.initiative_expr("r")
    live = (
        " AND r.deleted_at IS NULL"
        if "deleted_at" in SQLModel.metadata.tables[table].columns
        else ""
    )
    # Every fragment here is rendered from the registry above and the model
    # metadata — never from the request. The tables are named with their schema
    # so the probe does not depend on a search_path of its own.
    schema = guild_schema_name(guild_id)
    statement = text(
        f"SELECT {initiative} IS NULL OR EXISTS ("  # noqa: S608
        f'  SELECT 1 FROM "{schema}".initiative_members im'
        f"  WHERE im.initiative_id = {initiative} AND im.user_id = :uid)"
        f' FROM "{schema}".{table} r WHERE r.id = :rid{live}'
    )
    # Late-bound (module attribute at call time) so the test harness's
    # sessionmaker patch applies to the probe too.
    async with db_session.AdminSessionLocal() as probe, probe.begin():
        # One transaction, explicitly: the routing is transaction-local, and
        # the probe runs on a session of its own rather than the request's, so
        # it cannot inherit it.
        await set_rls_context(
            probe, guild_id=guild_id, guild_role=GuildRole.admin.value
        )
        found = (
            await probe.exec(statement, params={"uid": user_id, "rid": row_id})
        ).first()
    return bool(found[0]) if found is not None else False
