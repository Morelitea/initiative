"""the seat writes its own switches

Six columns on ``guilds`` say what a community asks of the people reaching it:
whether personal API keys are accepted, whether a second factor is required,
whether the session standard is held to, and what its notifications may leave
carrying. All six are the seat's surface, and the seat's routes already refuse
anybody who does not hold it — but the write itself ran on the system engine,
so the decision was the route's alone and the table had nothing to say.

``app_superadmin`` gets ``UPDATE`` on those six columns and nothing else on
``guilds``. Which row it may write is the table's own ``guild_update``
policy, which asks for the community this request is routed into and for an
administrator of it; the column list is what stops the same session touching a
name, an icon or a lifecycle status on its way past.

A column grant lives in ``pg_attribute``, not ``relacl``, so the registry in
``app.db.system_grants`` still records no table grant for this pair and
``security_invariants_test`` asserts the columns.

Revision ID: 20260923_0355
Revises: 20260922_0354
Create Date: 2026-09-23
"""

from alembic import op

revision = "20260923_0355"
down_revision = "20260922_0354"
branch_labels = None
depends_on = None

SEAT_FLOOR = "app_superadmin"

#: What a community asks of the people reaching it. Every one of these is set
#: by a route that takes the seat.
SEAT_COLUMNS = (
    "allow_api_keys",
    "require_second_factor",
    "enforce_compliance_session",
    "allow_push_notifications",
    "allow_email_notifications",
    "redact_notification_content",
)


def _on_seat_floor(statement: str) -> None:
    """Run ``statement`` if the seat floor exists.

    Guarded like the floor grants before it: the roles are cluster-global and
    a database restored beside another deployment's may not carry them.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SEAT_FLOOR}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    columns = ", ".join(SEAT_COLUMNS)
    _on_seat_floor(f"GRANT UPDATE ({columns}) ON public.guilds TO {SEAT_FLOOR}")


def downgrade() -> None:
    columns = ", ".join(SEAT_COLUMNS)
    _on_seat_floor(f"REVOKE UPDATE ({columns}) ON public.guilds FROM {SEAT_FLOOR}")
