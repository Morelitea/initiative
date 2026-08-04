"""force RLS on user_api_keys; move it to the system engine only

``user_api_keys`` is looked up by ``token_hash`` before the request's user is
resolved, so its access runs on the system engine (``app_admin``, BYPASSRLS)
rather than a request role — the same arrangement as ``auth_sessions``. This
migration makes that the enforced shape at the DB layer:

* ``ENABLE`` + ``FORCE ROW LEVEL SECURITY`` with no request-role policy (owners
  obey RLS too), so only the system engine reads or writes rows.
* ``REVOKE ALL`` from the request-path roles — ``app_user`` and the base roles
  the routed ``guild_<id>`` / ``platform_<tier>`` roles inherit from
  (``app_guild_base``, ``platform_base``) — on the table and its (legacy-named
  ``admin_api_keys_id_seq``) id sequence.
* ``app_admin`` keeps full DML (previously SELECT/DELETE; the lookup and create
  run there now) and USAGE on the id sequence.

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
