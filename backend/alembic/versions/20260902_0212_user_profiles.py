"""Give an account a public face: a custom status, and a look to wear.

Two JSONB columns on ``public.users``:

* ``custom_status`` — ``{"emoji": ..., "text": ...}``: what the person is up
  to, in their own words. One column rather than two, because it is one thing
  a person sets and one thing every surface that names them renders. Distinct
  from ``users.status``, which is the account's standing and is not theirs to
  write. Shape lives in ``app.schemas.platform.user.CustomStatus``.
* ``profile_decorations`` — a banner, a frame and badges, each held as an
  **id naming a catalog entry** rather than an image. The client resolves an id
  to artwork it already ships, so a decorated profile takes up none of a
  guild's upload allowance. An id this deployment doesn't know renders nothing,
  which is what lets a profile keep wearing something the store stopped
  offering. Shape lives in ``app.schemas.platform.user.ProfileDecorations``.

0144 replaced the request path's table-wide UPDATE on ``public.users`` with a
column list computed from the catalog at that revision, so a column added later
is not in it. The new ones are named explicitly below — the own-row policies
from 0202 still decide *whose* row they reach.

Nothing to carry in: every row starts with an empty status and an empty look,
from the server defaults.

Revision ID: 20260902_0212
Revises: 20260902_0211
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260902_0212"
down_revision = "20260902_0211"
branch_labels = None
depends_on = None

_COLUMNS = ("custom_status", "profile_decorations")


def _request_floors() -> tuple[str, ...]:
    """The request-path floors.

    ``app_user`` is the bare login role; ``app_guild_base`` is what every
    ``guild_<id>`` role inherits its shared-table access from; ``platform_base``
    is the platform-tier floor.
    """
    return (
        "app_user",
        "app_guild_base",
        f"{settings.PLATFORM_ROLE_PREFIX}platform_base",
    )


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "users",
            sa.Column(
                column,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    columns = ", ".join(_COLUMNS)
    for role in _request_floors():
        op.execute(f'GRANT UPDATE ({columns}) ON TABLE public.users TO "{role}"')


def downgrade() -> None:
    # Dropping the columns takes their column-level grants with them.
    for column in _COLUMNS:
        op.drop_column("users", column)
