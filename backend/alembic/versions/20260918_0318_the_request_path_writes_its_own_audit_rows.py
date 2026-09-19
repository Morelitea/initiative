"""the request path writes its own audit rows

An action is recorded in the transaction that performs it, on the session
that performs it. Only the system engine could insert into ``audit_events``,
which covered the surfaces that run there and none of the ones that run as
the routed roles: guild and initiative membership, sharing, a community's
own settings.

The request-path floors — the guild floor, its read-only twin, and the
platform floor — gain INSERT on the table and USAGE on its sequence, under
one policy: the row's ``actor_user_id`` is the session's own
``app.current_user_id`` — the account a request runs as, or nobody, for a
system sweep routed into a community with no account behind it. SELECT,
UPDATE and DELETE stay ungranted: the board reads on the system engine, and
nothing rewrites a record.

The table also gains an index on ``(guild_id, occurred_at)``: "what happened
in this community, recent first" is the question a tenant's record answers,
and every event about a community carries its id in that column.

Revision ID: 20260918_0318
Revises: 20260918_0317
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "20260918_0318"
down_revision = "20260918_0317"
branch_labels = None
depends_on = None

CURRENT_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

POLICY = "audit_events_request_insert"


def _request_floors() -> tuple[str, str, str]:
    return (
        "app_guild_base",
        "app_guild_base_ro",
        f"{settings.PLATFORM_ROLE_PREFIX}platform_base",
    )


def upgrade() -> None:
    op.create_index(
        "ix_audit_events_guild", "audit_events", ["guild_id", "occurred_at"]
    )
    floors = ", ".join(f'"{role}"' for role in _request_floors())
    for statement in (
        f"GRANT INSERT ON TABLE public.audit_events TO {floors}",
        f"GRANT USAGE ON SEQUENCE public.audit_events_id_seq TO {floors}",
        f"CREATE POLICY {POLICY} ON public.audit_events "
        f"AS PERMISSIVE FOR INSERT TO {floors} "
        f"WITH CHECK (actor_user_id IS NOT DISTINCT FROM {CURRENT_USER_ID})",
    ):
        op.execute(statement)


def downgrade() -> None:
    floors = ", ".join(f'"{role}"' for role in _request_floors())
    for statement in (
        f"DROP POLICY IF EXISTS {POLICY} ON public.audit_events",
        f"REVOKE USAGE ON SEQUENCE public.audit_events_id_seq FROM {floors}",
        f"REVOKE INSERT ON TABLE public.audit_events FROM {floors}",
    ):
        op.execute(statement)
    op.drop_index("ix_audit_events_guild", table_name="audit_events")
