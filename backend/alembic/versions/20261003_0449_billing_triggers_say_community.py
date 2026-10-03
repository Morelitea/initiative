"""billing triggers say community

The two triggers that keep a billing-managed deployment's plans and statuses
billing's refuse other writers with ``COMMUNITY_PLAN_SET_BY_BILLING`` and
``COMMUNITY_STATUS_SET_BY_BILLING``, the codes the API answers with for the
same refusal. Only the raised messages change.

Revision ID: 20261003_0449
Revises: 20261003_0448
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "20261003_0449"
down_revision = "20261003_0448"
branch_labels = None
depends_on = None


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _plan_trigger_function(code: str) -> str:
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
        RAISE EXCEPTION '{code}'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$function$"""


def _status_trigger_function(code: str) -> str:
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
            RAISE EXCEPTION '{code}'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status IN ('suspended', 'deleted') THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ('suspended', 'deleted') THEN
        SELECT a.billing_status INTO recorded
        FROM public.guild_administration a
        WHERE a.guild_id = NEW.id;
        IF NEW.status = COALESCE(recorded, 'active') THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION '{code}'
        USING ERRCODE = 'insufficient_privilege';
END
$function$"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_plan_trigger_function("COMMUNITY_PLAN_SET_BY_BILLING"))
    op.execute(_status_trigger_function("COMMUNITY_STATUS_SET_BY_BILLING"))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_plan_trigger_function("GUILD_PLAN_SET_BY_BILLING"))
    op.execute(_status_trigger_function("GUILD_STATUS_SET_BY_BILLING"))
