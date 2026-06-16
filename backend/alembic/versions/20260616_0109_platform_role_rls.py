"""Phase 2 platform-role RLS: least-privilege policies on the purely-platform
tables (``users``, ``access_grants``, ``app_settings``).

Phase 1 (migration 0106) created the ``platform_<tier>`` ladder + ``platform_base``
floor and routes the public/platform request path through ``SET ROLE
platform_<tier>``, but left RLS untouched — every tier still behaved like the broad
login role. This migration adds the DB backstop the design's §4 calls for: a
``platform_base`` own-row floor plus per-tier ``TO platform_<tier>`` policies, so a
tier *physically cannot* exceed its privilege on these tables even if a handler
forgets its capability check.

Scope — the three **purely-platform** tables (no guild-path entanglement):

* ``users`` (identity). Decompose the wide-open ``users_open`` (``TO PUBLIC USING
  (true)``) into:
    - ``users_app_floor`` — broad ``TO app_user`` floor that preserves the
      unauthenticated / bootstrap surface (login, register, password reset, OIDC)
      and service-layer callers that run as the bare login role. The doc's §5
      ``app_user`` narrowing stays deferred (Phase 1 explained why): this only
      stops the *authenticated platform path* (``platform_<tier>``) from inheriting
      god-mode on ``users``.
    - ``users_guild_floor`` — broad ``TO app_guild_base`` floor preserving the guild
      path's existing access to the shared ``users`` table (assignees, comment
      authors, members, mentions, per-user AI settings write). Narrowing
      app_guild_base is out of scope for this pass (design §1).
    - ``users_platform_self`` — ``TO platform_base`` own-row (read/update self): the
      member-tier floor.
    - ``users_platform_read`` — ``TO platform_support+`` read-all (``users.read``).
    - ``users_platform_manage`` — ``TO platform_moderator+`` update-all
      (``users.manage``).
  ``users_no_delete`` (RESTRICTIVE DELETE deny) is kept: user deletion is a
  cross-schema cascade that stays on the ``app_admin`` engine.

* ``access_grants`` (PAM). Retire ``is_superadmin``: own rows for everyone (the
  requester, and the ``get_live_grant`` lookup on the guild-routing path, which
  runs as ``app_user`` and filters ``user_id``); ``platform_admin+`` manage the full
  queue (``access.read`` / ``access.approve``).

* ``app_settings`` (owner-only config). ENABLE+FORCE RLS; everyone may SELECT
  (public reads: interface colors, role labels, OIDC status, FCM); only
  ``platform_owner`` may write — enforced at BOTH the RLS layer (``TO
  platform_owner``) and the table GRANT (write revoked from ``app_user`` /
  ``platform_base``, granted to ``platform_owner``), per §4. ``app_admin``
  (BYPASSRLS + standing ALL grant) keeps writing for startup ``ensure_defaults``
  and the admin config endpoints. The lazy singleton create/reseed on read is made
  privilege-tolerant in ``app.services.app_settings`` so a non-owner read returns a
  transient default instead of faulting.

NOT in scope (deferred to Phase 3, per §11): the dual-path tables (``guilds``,
``guild_memberships``, ``guild_invites``, ``oidc_claim_mappings``) keep their
``is_superadmin`` leg — removing it before break-glass exists would lock admins out
of a guild mid-migration. ``is_superadmin`` is therefore retired only from the
policies this migration rewrites; the GUC is still set on the public path
(``get_user_session``) but is inert for these three tables (no policy references
it).

Role names carry ``settings.PLATFORM_ROLE_PREFIX`` (empty in prod/dev; ``test_…``
under the suite) read at apply time, matching the roles migration 0106 created.
``app_user`` is the fixed, unprefixed login role from the baseline.

Revision ID: 20260616_0109
Revises: 20260616_0108
Create Date: 2026-06-16
"""

from alembic import op
from sqlalchemy import text

from app.core.config import settings
from app.db.schema_provisioning import platform_role_name

revision = "20260616_0109"
down_revision = "20260616_0108"
branch_labels = None
depends_on = None

# Row-owner predicate (mirrors the baseline constant). NULLIF-guarded so an unset
# context casts cleanly instead of faulting the whole query.
USER_ID = (
    "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
)


def _base_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _role_list(*tiers: str) -> str:
    """Quoted, comma-joined ``platform_<tier>`` role names for a ``TO`` clause."""
    return ", ".join(f'"{platform_role_name(t)}"' for t in tiers)


def upgrade() -> None:
    conn = op.get_bind()
    base = _base_role()
    owner = platform_role_name("owner")
    support_plus = _role_list("support", "moderator", "admin", "owner")
    moderator_plus = _role_list("moderator", "admin", "owner")
    admin_plus = _role_list("admin", "owner")

    # ---- users -------------------------------------------------------------
    conn.execute(text("DROP POLICY IF EXISTS users_open ON users"))
    conn.execute(
        text(
            "CREATE POLICY users_app_floor ON users AS PERMISSIVE FOR ALL "
            'TO "app_user" USING (true) WITH CHECK (true)'
        )
    )
    # Guild-path floor. ``users`` is a shared table the guild path reads/writes
    # constantly (assignees, comment authors, members, mentions, and the per-user AI
    # settings write), under ``guild_<id>`` / ``guild_<id>_ro`` roles that inherit
    # ``app_guild_base``. Preserve that access verbatim — narrowing app_guild_base is
    # explicitly out of scope for this pass (design §1); this only de-couples the
    # platform path. The read-only PAM role is still write-blocked by its own GRANT.
    conn.execute(
        text(
            "CREATE POLICY users_guild_floor ON users AS PERMISSIVE FOR ALL "
            'TO "app_guild_base" USING (true) WITH CHECK (true)'
        )
    )
    conn.execute(
        text(
            f"CREATE POLICY users_platform_self ON users AS PERMISSIVE FOR ALL "
            f'TO "{base}" USING (id = ({USER_ID})) WITH CHECK (id = ({USER_ID}))'
        )
    )
    conn.execute(
        text(
            f"CREATE POLICY users_platform_read ON users AS PERMISSIVE FOR SELECT "
            f"TO {support_plus} USING (true)"
        )
    )
    conn.execute(
        text(
            f"CREATE POLICY users_platform_manage ON users AS PERMISSIVE FOR UPDATE "
            f"TO {moderator_plus} USING (true) WITH CHECK (true)"
        )
    )
    # users_no_delete (RESTRICTIVE DELETE deny) is intentionally retained.

    # ---- access_grants -----------------------------------------------------
    conn.execute(
        text("DROP POLICY IF EXISTS access_grants_self_or_super ON access_grants")
    )
    conn.execute(
        text(
            f"CREATE POLICY access_grants_self ON access_grants AS PERMISSIVE FOR ALL "
            f"TO PUBLIC USING (user_id = ({USER_ID})) "
            f"WITH CHECK (user_id = ({USER_ID}))"
        )
    )
    conn.execute(
        text(
            f"CREATE POLICY access_grants_admin ON access_grants AS PERMISSIVE FOR ALL "
            f"TO {admin_plus} USING (true) WITH CHECK (true)"
        )
    )

    # ---- app_settings (owner-only config) ----------------------------------
    conn.execute(text("ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY"))
    conn.execute(text("ALTER TABLE ONLY app_settings FORCE ROW LEVEL SECURITY"))
    # SELECT stays broad ON PURPOSE: the singleton row is read by app_user on
    # unauthenticated/service paths that have no owner tier to assume — the OIDC
    # login/callback flow (decrypts oidc_client_secret) and the email service
    # (decrypts smtp_password) both need it. Owner-only READ at the DB would break
    # those. The owner-only boundary is on WRITES (policy + GRANT below); the
    # owner-gated config-read *endpoints* run owner-scoped (UserSessionDep) at the
    # app layer, and the sensitive columns are encrypted at rest (SECRET_KEY), so a
    # broad SELECT exposes only ciphertext. A future column-level split of public
    # branding vs sensitive config could tighten this; out of scope here.
    conn.execute(
        text(
            "CREATE POLICY app_settings_read ON app_settings AS PERMISSIVE FOR SELECT "
            "TO PUBLIC USING (true)"
        )
    )
    conn.execute(
        text(
            f"CREATE POLICY app_settings_owner ON app_settings AS PERMISSIVE FOR ALL "
            f'TO "{owner}" USING (true) WITH CHECK (true)'
        )
    )
    # Owner-only at the GRANT layer too (§4). app_admin keeps its standing ALL grant
    # (BYPASSRLS engine: startup ensure_defaults + admin config writes).
    conn.execute(text('REVOKE INSERT, UPDATE, DELETE ON app_settings FROM "app_user"'))
    conn.execute(text(f'REVOKE INSERT, UPDATE, DELETE ON app_settings FROM "{base}"'))
    conn.execute(text(f'GRANT INSERT, UPDATE, DELETE ON app_settings TO "{owner}"'))


def downgrade() -> None:
    conn = op.get_bind()
    base = _base_role()
    owner = platform_role_name("owner")

    # ---- app_settings ----
    conn.execute(text(f'REVOKE INSERT, UPDATE, DELETE ON app_settings FROM "{owner}"'))
    conn.execute(text(f'GRANT INSERT, UPDATE, DELETE ON app_settings TO "{base}"'))
    conn.execute(text('GRANT INSERT, UPDATE, DELETE ON app_settings TO "app_user"'))
    conn.execute(text("DROP POLICY IF EXISTS app_settings_owner ON app_settings"))
    conn.execute(text("DROP POLICY IF EXISTS app_settings_read ON app_settings"))
    conn.execute(text("ALTER TABLE app_settings NO FORCE ROW LEVEL SECURITY"))
    conn.execute(text("ALTER TABLE app_settings DISABLE ROW LEVEL SECURITY"))

    # ---- access_grants ----
    conn.execute(text("DROP POLICY IF EXISTS access_grants_admin ON access_grants"))
    conn.execute(text("DROP POLICY IF EXISTS access_grants_self ON access_grants"))
    is_super = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
    conn.execute(
        text(
            f"CREATE POLICY access_grants_self_or_super ON access_grants FOR ALL "
            f"USING ((user_id = ({USER_ID})) OR ({is_super})) "
            f"WITH CHECK ((user_id = ({USER_ID})) OR ({is_super}))"
        )
    )

    # ---- users ----
    conn.execute(text("DROP POLICY IF EXISTS users_platform_manage ON users"))
    conn.execute(text("DROP POLICY IF EXISTS users_platform_read ON users"))
    conn.execute(text("DROP POLICY IF EXISTS users_platform_self ON users"))
    conn.execute(text("DROP POLICY IF EXISTS users_guild_floor ON users"))
    conn.execute(text("DROP POLICY IF EXISTS users_app_floor ON users"))
    conn.execute(
        text(
            "CREATE POLICY users_open ON users AS PERMISSIVE FOR ALL "
            "USING (true) WITH CHECK (true)"
        )
    )
