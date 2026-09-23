"""billing sets the plan

On a deployment whose plans are set by its billing service, the plan columns
of ``guild_administration`` and the lifecycle status of ``guilds`` are
billing's, and the database holds every other writer to that.

* ``public.billing_managed()`` answers whether this deployment is one. Created
  here answering ``false``; the boot sequence renders it from the environment
  (``app.db.billing_managed``) over the provisioning login, which owns it.
* ``guild_administration.billing_status`` records the status billing last
  wrote, including one a suspended guild did not take. Backfilled from the
  guild's own status where billing could have set it.
* ``guild_plan_follows_billing`` (``BEFORE UPDATE`` on
  ``guild_administration``): while billing-managed, only the billing role
  changes the row.
* ``guild_status_follows_billing`` (``BEFORE UPDATE OF status`` on ``guilds``):
  while billing-managed, the billing role moves a guild between the statuses
  it sets and never into or out of ``suspended`` or ``deleted``; every other
  role moves it into ``suspended``, from ``suspended`` to ``billing_status``,
  into ``deleted``, or out of ``deleted``.
* A ``billing`` access grant has one level, ``read``.

Revision ID: 20260923_0362
Revises: 20260923_0361
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260923_0362"
down_revision = "20260923_0361"
branch_labels = None
depends_on = None

# The vocabularies as of THIS revision, spelled out rather than read from the
# model.
_BILLING_STATUSES = ("active", "read_only", "on_hold")
_CONTENT_LEVELS = ("read", "read_write")
_SETTINGS_LEVELS = ("admin", "superadmin")

_STATUS_CK = "ck_guild_administration_billing_status"
_LEVEL_CK = "ck_access_grants_access_level"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


_LEVEL_RULE = (
    f"(purpose = 'settings' AND access_level IN ({_quoted(_SETTINGS_LEVELS)}))"
    " OR (purpose = 'billing' AND access_level = 'read')"
    f" OR (purpose NOT IN ('settings', 'billing')"
    f" AND access_level IN ({_quoted(_CONTENT_LEVELS)}))"
)
_PRIOR_LEVEL_RULE = (
    f"(purpose = 'settings' AND access_level IN ({_quoted(_SETTINGS_LEVELS)}))"
    f" OR (purpose <> 'settings' AND access_level IN ({_quoted(_CONTENT_LEVELS)}))"
)


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


BILLING_MANAGED = """\
CREATE OR REPLACE FUNCTION public.billing_managed()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$ SELECT false $function$"""


def _plan_trigger_function() -> str:
    return f"""\
CREATE OR REPLACE FUNCTION public.guild_plan_follows_billing()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF current_user = '{_billing_role()}' OR NOT public.billing_managed() THEN
        RETURN NEW;
    END IF;
    IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'GUILD_PLAN_SET_BY_BILLING'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$function$"""


def _status_trigger_function() -> str:
    return f"""\
CREATE OR REPLACE FUNCTION public.guild_status_follows_billing()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    recorded text;
BEGIN
    IF NEW.status IS NOT DISTINCT FROM OLD.status
       OR NOT public.billing_managed() THEN
        RETURN NEW;
    END IF;
    IF current_user = '{_billing_role()}' THEN
        IF OLD.status IN ('suspended', 'deleted')
           OR NEW.status IN ('suspended', 'deleted') THEN
            RAISE EXCEPTION 'GUILD_STATUS_SET_BY_BILLING'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status IN ('suspended', 'deleted') OR OLD.status = 'deleted' THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'suspended' THEN
        SELECT a.billing_status INTO recorded
        FROM public.guild_administration a
        WHERE a.guild_id = NEW.id;
        IF NEW.status = COALESCE(recorded, 'active') THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'GUILD_STATUS_SET_BY_BILLING'
        USING ERRCODE = 'insufficient_privilege';
END
$function$"""


def upgrade() -> None:
    if not _is_postgres():
        return
    role = _billing_role()

    op.add_column(
        "guild_administration",
        sa.Column("billing_status", sa.String(16), nullable=True),
    )
    op.create_check_constraint(
        _STATUS_CK,
        "guild_administration",
        f"billing_status IS NULL OR billing_status IN ({_quoted(_BILLING_STATUSES)})",
    )
    # The table is FORCE ROW LEVEL SECURITY and this migration carries no
    # request context, so the backfill lifts FORCE for its own write.
    op.execute("ALTER TABLE public.guild_administration NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            "UPDATE public.guild_administration a SET billing_status = g.status "
            "FROM public.guilds g WHERE g.id = a.guild_id "
            f"AND g.status IN ({_quoted(_BILLING_STATUSES)})"
        )
    finally:
        op.execute("ALTER TABLE public.guild_administration FORCE ROW LEVEL SECURITY")
    op.execute(
        f'GRANT SELECT (billing_status) ON public.guild_administration TO "{role}"'
    )
    op.execute(
        f'GRANT UPDATE (billing_status) ON public.guild_administration TO "{role}"'
    )

    op.execute(BILLING_MANAGED)
    op.execute(_plan_trigger_function())
    op.execute(_status_trigger_function())
    op.execute(
        "CREATE TRIGGER guild_plan_follows_billing "
        "BEFORE UPDATE ON public.guild_administration "
        "FOR EACH ROW EXECUTE FUNCTION public.guild_plan_follows_billing()"
    )
    op.execute(
        "CREATE TRIGGER guild_status_follows_billing "
        "BEFORE UPDATE OF status ON public.guilds "
        "FOR EACH ROW EXECUTE FUNCTION public.guild_status_follows_billing()"
    )

    op.drop_constraint(_LEVEL_CK, "access_grants", type_="check")
    op.create_check_constraint(_LEVEL_CK, "access_grants", _LEVEL_RULE)


def downgrade() -> None:
    if not _is_postgres():
        return
    role = _billing_role()

    op.drop_constraint(_LEVEL_CK, "access_grants", type_="check")
    op.create_check_constraint(_LEVEL_CK, "access_grants", _PRIOR_LEVEL_RULE)

    op.execute("DROP TRIGGER IF EXISTS guild_status_follows_billing ON public.guilds")
    op.execute(
        "DROP TRIGGER IF EXISTS guild_plan_follows_billing "
        "ON public.guild_administration"
    )
    op.execute("DROP FUNCTION IF EXISTS public.guild_status_follows_billing()")
    op.execute("DROP FUNCTION IF EXISTS public.guild_plan_follows_billing()")
    op.execute("DROP FUNCTION IF EXISTS public.billing_managed()")

    op.execute(
        f'REVOKE UPDATE (billing_status) ON public.guild_administration FROM "{role}"'
    )
    op.execute(
        f'REVOKE SELECT (billing_status) ON public.guild_administration FROM "{role}"'
    )
    op.drop_constraint(_STATUS_CK, "guild_administration", type_="check")
    op.drop_column("guild_administration", "billing_status")
