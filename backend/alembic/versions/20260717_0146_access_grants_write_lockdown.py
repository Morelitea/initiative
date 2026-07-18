"""Restrict public.access_grants writes to the system engine.

Access grants are created and transitioned only through the ``/access-grants``
endpoints, which run on the system engine (``app_admin``) behind
``access.request`` / ``access.approve`` / ``data.bypass`` capability checks. No
request-path flow writes the table.

Revoke INSERT/UPDATE/DELETE on ``access_grants`` from the request-path floors
(``app_guild_base`` — every ``guild_<id>`` role — and ``platform_base``),
keeping SELECT (a grantee reads their own live grant when a guild session is
established). ``app_admin`` (BYPASSRLS system engine) is unchanged. Same shape
as the users/guild_memberships write lockdown in 0144/0145.
"""

from alembic import op

from app.core.config import settings

revision = "20260717_0146"
down_revision = "20260717_0145"
branch_labels = None
depends_on = None


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    base = _platform_base()
    for role in ("app_guild_base", f'"{base}"'):
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE ON TABLE public.access_grants FROM {role}"
        )


def downgrade() -> None:
    base = _platform_base()
    for role in ("app_guild_base", f'"{base}"'):
        op.execute(
            f"GRANT INSERT, UPDATE, DELETE ON TABLE public.access_grants TO {role}"
        )
