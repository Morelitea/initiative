"""Column-scope the guild-facing write path on public.guilds.

``guilds`` carries two very different kinds of columns:

* identity a guild's own admins may edit (``name`` / ``description`` /
  ``icon_base64`` and the ``updated_at`` stamp), and
* operator/billing enforcement inputs (``status`` / ``status_changed_at`` /
  ``tier_name`` / ``max_storage_bytes`` / ``max_users``) that only the platform
  operator endpoint (system engine) and the verified billing path
  (``initiative_billing``, already column-scoped in 0134) may set.

Until now the guild-role floor (``app_guild_base``) and the platform-tier floor
(``platform_base``) held a table-wide UPDATE (plus INSERT neither ever uses),
so the separation existed only in app code. Make the database authoritative:

* ``app_guild_base``: UPDATE only on the identity columns; keeps SELECT and
  DELETE (guild deletion runs as the assumed ``guild_<id>`` role).
* ``platform_base``: SELECT only — no request path writes ``guilds`` as a
  platform tier (create/accept-invite run on the system engine).
"""

from alembic import op

from app.core.config import settings

revision = "20260709_0138"
down_revision = "20260709_0137"
branch_labels = None
depends_on = None

# Columns a guild's own admin edits through PATCH /guilds/{guild_id}.
_GUILD_ADMIN_COLUMNS = "name, description, icon_base64, updated_at"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    base = _platform_base()
    for statement in [
        f'REVOKE INSERT, UPDATE, DELETE ON TABLE public.guilds FROM "{base}"',
        "REVOKE INSERT, UPDATE ON TABLE public.guilds FROM app_guild_base",
        f"GRANT UPDATE ({_GUILD_ADMIN_COLUMNS}) ON TABLE public.guilds "
        "TO app_guild_base",
    ]:
        op.execute(statement)


def downgrade() -> None:
    base = _platform_base()
    for statement in [
        "REVOKE UPDATE ON TABLE public.guilds FROM app_guild_base",
        "GRANT INSERT, UPDATE ON TABLE public.guilds TO app_guild_base",
        f'GRANT INSERT, UPDATE, DELETE ON TABLE public.guilds TO "{base}"',
    ]:
        op.execute(statement)
