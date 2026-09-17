"""Every community already entitled to something keeps its Authentication tab

``restrictions`` is new and off by default, which is the answer for almost
every community: no providers of its own, no sign-in requirement, no refusing
personal API keys, no session standard, and no tab to read any of it on.

A community an operator has already granted something is a different case. It
has the surface today, so it is granted the master here and keeps it — the
nesting changes who may reach the tab from now on, not who has it.

Counted rather than asserting a rowcount: a deployment that has granted nobody
anything has nothing to grant here.

Revision ID: 20260917_0302
Revises: 20260917_0301
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0302"
down_revision = "20260917_0301"
branch_labels = None
depends_on = None

_MASTER = "'restrictions'::guild_auth_option"

_GRANT = (
    "UPDATE public.guild_administration "
    f"SET auth_options = {_MASTER} || auth_options "
    f"WHERE auth_options <> '{{}}' AND NOT ({_MASTER} = ANY(auth_options))"
)

_WITHDRAW = (
    "UPDATE public.guild_administration "
    f"SET auth_options = array_remove(auth_options, {_MASTER}) "
    f"WHERE {_MASTER} = ANY(auth_options)"
)

_MISSING = (
    "SELECT count(*) FROM public.guild_administration "
    f"WHERE auth_options <> '{{}}' AND NOT ({_MASTER} = ANY(auth_options))"
)


def _run(
    conn, statement: str, *, check: str | None = None, complaint: str = ""
) -> None:
    op.execute("ALTER TABLE public.guild_administration NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(sa.text(statement))
        if check is not None:
            left = conn.execute(sa.text(check)).scalar_one()
            assert left == 0, complaint.format(left)
    finally:
        op.execute("ALTER TABLE public.guild_administration FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    _run(
        conn,
        _GRANT,
        check=_MISSING,
        complaint="{} entitled communities did not get the master option",
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    _run(conn, _WITHDRAW)
