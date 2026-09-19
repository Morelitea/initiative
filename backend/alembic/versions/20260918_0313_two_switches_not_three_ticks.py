"""two switches, not three nested ticks

What an operator may let a community decide for itself was three values in a
ladder: ``restrictions`` as the master, with ``providers`` and
``require_sign_in`` beneath it. The ladder read them as degrees of one thing.
They are two unrelated things that happened to share a tab.

``restrictions`` gated two write endpoints — personal API keys and session
length — *and* acted as the master for the provider ticks. Nothing connects
those jobs, and a community wanting single sign-on got the compliance knobs as
a side effect.

``providers`` and ``require_sign_in`` should never have been two. That split's
justification — offering a way in is smaller than insisting on one — predates
community-written group rules. A community holding ``providers`` already
decides who is in it and at what rank, including as an **admin**, which makes
the requirement the smaller of the two powers and the odd one to gate
separately.

So: two values, neither nested under the other, both keeping the names that
describe what they now do. ``restrictions`` is the restrictions a community
puts on itself; ``providers`` is everything that follows from a provider.

**``require_sign_in`` goes.** Postgres has no ``ALTER TYPE ... DROP VALUE``, so
the type is recreated without it — the ordinary way, and worth doing rather
than leaving a retired label in the type for somebody to wonder about later.
One column depends on it (``guild_administration.auth_options``) and one
default, both handled below.

**Two row fixes, before the type can be rebuilt.**

1. Every row carrying ``require_sign_in`` is stripped of it, or the cast in
   step 3 has nowhere to put it. A community that held it keeps ``providers``,
   which now carries the same authority.
2. Rows holding ``providers`` with no ``restrictions`` are cleared. That shape
   could never be *set* — the operator's sheet disables the sub-tick without
   the master — but it could be *left*: the sheet removes only the value
   clicked and the master's own tick is not disabled, so ticking both and
   unticking the master stored ``['providers']``. ``effective_options``
   discarded it and no screen showed it. Once the master goes, a discarded
   value starts counting, and those are communities an operator explicitly
   withdrew the grant from — the worst population to hand it back to silently.

A fresh install has no rows, so neither fix runs there and CI is green either
way. ``guild_auth_options_test`` is what checks them instead.

Revision ID: 20260918_0313
Revises: 20260918_0312
Create Date: 2026-09-18
"""

from alembic import op

revision = "20260918_0313"
down_revision = "20260918_0312"
branch_labels = None
depends_on = None

TABLE = "public.guild_administration"
TYPE = "public.guild_auth_option"


def _strip(values: str) -> str:
    """An UPDATE removing the named values from ``auth_options``."""
    excluded = " AND ".join(
        f"option <> '{v}'::guild_auth_option" for v in values.split()
    )
    held = " OR ".join(
        f"'{v}'::guild_auth_option = ANY(auth_options)" for v in values.split()
    )
    return f"""
        UPDATE {TABLE}
        SET auth_options = (
            SELECT COALESCE(
                array_agg(option ORDER BY option),
                ARRAY[]::guild_auth_option[]
            )
            FROM unnest(auth_options) AS option
            WHERE {excluded}
        )
        WHERE auth_options IS NOT NULL AND ({held})
    """


def upgrade() -> None:
    # ``guild_administration`` FORCEs row-level security, which binds the owner
    # this migration runs as, and its policies key on request GUCs a migration
    # has no value for. Lifted for the two row fixes and restored in the same
    # transaction, the way 0302 writes to it.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        _fix_rows()
    finally:
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")

    # ── 3. The type without the retired value ─────────────────────────────
    #
    # The default names the type, so it comes off first and goes back after.
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN auth_options DROP DEFAULT")
    op.execute(f"ALTER TYPE {TYPE} RENAME TO guild_auth_option_old")
    op.execute(f"CREATE TYPE {TYPE} AS ENUM ('providers', 'restrictions')")
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN auth_options TYPE guild_auth_option[] "
        f"USING auth_options::text[]::guild_auth_option[]"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN auth_options "
        f"SET DEFAULT '{{}}'::guild_auth_option[]"
    )
    op.execute("DROP TYPE public.guild_auth_option_old")


def _fix_rows() -> None:
    # ── 1. The withdrawn grants, while the master still means something ───
    op.execute(
        f"""
        UPDATE {TABLE}
        SET auth_options = (
            SELECT COALESCE(
                array_agg(option ORDER BY option),
                ARRAY[]::guild_auth_option[]
            )
            FROM unnest(auth_options) AS option
            WHERE option <> 'providers'::guild_auth_option
              AND option <> 'require_sign_in'::guild_auth_option
        )
        WHERE auth_options IS NOT NULL
          AND NOT ('restrictions'::guild_auth_option = ANY(auth_options))
          AND (
              'providers'::guild_auth_option = ANY(auth_options)
              OR 'require_sign_in'::guild_auth_option = ANY(auth_options)
          )
        """
    )

    # ── 2. The retired value, off every remaining row ─────────────────────
    op.execute(_strip("require_sign_in"))


def downgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN auth_options DROP DEFAULT")
    op.execute(f"ALTER TYPE {TYPE} RENAME TO guild_auth_option_old")
    op.execute(
        f"CREATE TYPE {TYPE} AS ENUM ('providers', 'require_sign_in', 'restrictions')"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN auth_options TYPE guild_auth_option[] "
        f"USING auth_options::text[]::guild_auth_option[]"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN auth_options "
        f"SET DEFAULT '{{}}'::guild_auth_option[]"
    )
    op.execute("DROP TYPE public.guild_auth_option_old")
    # The rows are not restored: one held a value this revision folded into
    # another, and the other held a grant the old rules already discarded.
