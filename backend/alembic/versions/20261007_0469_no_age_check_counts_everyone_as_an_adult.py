"""No age check counts everyone as an adult

``dm_reachable`` held an account out of direct messages until it had answered
the age question, on every deployment. A deployment whose owner has turned the
age check off (``app_settings.community_age_gate_enabled``) never asks it, so
none of its accounts could be messaged. The rule now reads the switch: with it
off, every active account is reachable.

The reader gains ``SELECT`` on the singleton's id and that one column of
``app_settings``, which every role reads under ``app_settings_read``.

Revision ID: 20261007_0469
Revises: 20261006_0468
Create Date: 2026-10-07
"""

from alembic import op

revision = "20261007_0469"
down_revision = "20261006_0468"
branch_labels = None
depends_on = None

#: The reader role that owns the DM rule's functions (0223, 0417).
READER = "app_dm_reader"

_GRANT = (
    "GRANT SELECT (id, community_age_gate_enabled) ON TABLE public.app_settings "
    f'TO "{READER}"'
)
_REVOKE = (
    "REVOKE SELECT (id, community_age_gate_enabled) ON TABLE public.app_settings "
    f'FROM "{READER}"'
)


def _reachable(age_rule: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION public.dm_reachable(account_id int)
    RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $fn$
      SELECT EXISTS (
        SELECT 1 FROM public.users u
        WHERE u.id = account_id
          AND u.status = 'active'
          AND {age_rule}
      )
    $fn$
    """


#: Answered, or not asked on this deployment.
_ANSWERED_OR_NOT_ASKED = """(
            u.age_confirmed_at IS NOT NULL
            OR NOT COALESCE(
              (SELECT s.community_age_gate_enabled
                 FROM public.app_settings s WHERE s.id = 1),
              true
            )
          )"""

#: 0223's rule.
_ANSWERED = "u.age_confirmed_at IS NOT NULL"


def upgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(_GRANT)
    op.execute(_reachable(_ANSWERED_OR_NOT_ASKED))


def downgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(_reachable(_ANSWERED))
    op.execute(_REVOKE)
