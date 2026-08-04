"""force RLS on user_api_keys; move it to the system engine only

``user_api_keys`` is a pre-auth credential store: it is validated by
``token_hash`` *before the user is known*, so the lookup can't run under an
own-row policy — it runs BYPASSRLS on the system engine (``app_admin``), exactly
like ``auth_sessions``. This migration makes the DB the enforcement point:

* ``ENABLE`` + ``FORCE ROW LEVEL SECURITY`` with **no** request-role policy, so
  only the BYPASSRLS system engine can read/write rows (owners obey RLS too).
* ``REVOKE ALL`` from the request-path roles — the two directly-granted login
  roles (``app_user``) and the base roles the routed ``guild_<id>`` /
  ``platform_<tier>`` roles inherit from (``app_guild_base``, ``platform_base``)
  — so no request-path role can touch the table (grant *and* RLS both deny).
* ``app_admin`` keeps full DML (it previously held only SELECT/DELETE; the auth
  lookup + create now run there too). Its USAGE on the id sequence
  (legacy-named ``admin_api_keys_id_seq``) is already granted; re-granted here so
  the INSERT path is self-contained.

Registry mirror: ``SHARED_TABLE_SYSTEM_GRANTS['user_api_keys']`` becomes full
DML and ``SHARED_TABLE_APP_USER_GRANTS['user_api_keys']`` becomes ``None`` (see
app/db/system_grants.py); the RLS-forced set gains ``user_api_keys`` (see
security_invariants_test).
"""

from alembic import op

from app.core.config import settings

revision = "20260803_0156"
down_revision = "20260803_0155"
branch_labels = None
depends_on = None

_SEQUENCE = "public.admin_api_keys_id_seq"


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    base = _platform("base")
    _run(
        [
            "ALTER TABLE public.user_api_keys ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.user_api_keys FORCE ROW LEVEL SECURITY",
            "REVOKE ALL ON TABLE public.user_api_keys "
            f'FROM app_guild_base, "{base}", app_user',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            "public.user_api_keys TO app_admin",
            # The INSERT path (create key) now runs on the system engine, so it
            # needs the id sequence; strip the request roles to match the table.
            f"REVOKE ALL ON SEQUENCE {_SEQUENCE} "
            f'FROM app_guild_base, "{base}", app_user',
            f"GRANT USAGE, SELECT ON SEQUENCE {_SEQUENCE} TO app_admin",
        ]
    )


def downgrade() -> None:
    base = _platform("base")
    _run(
        [
            "ALTER TABLE public.user_api_keys NO FORCE ROW LEVEL SECURITY",
            "ALTER TABLE public.user_api_keys DISABLE ROW LEVEL SECURITY",
            # Restore the pre-migration grant surface: request-path roles regain
            # full DML, app_admin drops back to SELECT/DELETE.
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            f'public.user_api_keys TO app_guild_base, "{base}", app_user',
            "REVOKE INSERT, UPDATE ON TABLE public.user_api_keys FROM app_admin",
            f"GRANT USAGE, SELECT ON SEQUENCE {_SEQUENCE} "
            f'TO app_guild_base, "{base}", app_user',
        ]
    )
