"""Post-squash reconciler: bring any pre-collapse database to the baseline state.

The collapsed baseline (20260626_0125) only RUNS on fresh databases — every
v0.53.2+ deployment is already stamped at that id and skips it. This single
migration is everything such a deployment needs on top, folded from the
pre-release 0126–0130 chain (none of which ever shipped):

1. **Conversion guard** — a legacy database whose guilds still have
   unconverted rows in the frozen public copies aborts with step-through-
   v0.53.x instructions (the only data-loss window).
2. **guild_template** — created from the frozen baseline snapshot when absent
   (fresh installs already have it from the baseline itself).
3. **Fleet healing** — guild-schema column defaults re-pointed off public
   sequences (via pg_depend), cross-schema FKs to the frozen copies dropped,
   dead legacy objects removed.
4. **Superadmin retirement** — the 14 shared-table policies recreated without
   their dead ``is_superadmin`` legs.
5. **Grant matrices** — ``app_admin`` (system engine) and ``app_user`` (bare
   login role) reduced to their audited per-table verbs; blanket future-table
   default privileges revoked for both.

Everything is idempotent, so the fresh-install replay right after the baseline
is a harmless re-assert. Downgrade is intentionally unsupported: this is a
healing/reconciliation step over states that no longer have code paths.

Revision ID: 20260702_0126
Revises: 20260626_0125
Create Date: 2026-07-02
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import guild_schema_names, split_sql_statements

revision = "20260702_0126"
down_revision = "20260626_0125"
branch_labels = None
depends_on = None

_TEMPLATE_SQL_PATH = (
    Path(__file__).resolve().parents[1] / "baseline" / "guild_template_0125.sql"
)

# --- 1. conversion guard (from the pre-release 0126) -------------------------

# Marker comment the (now removed) startup conversion stamped on a guild schema
# once its public rows were fully copied in — see the deleted
# app/db/guild_conversion.py; frozen here as part of the migration record.
_CONVERSION_MARKER = "schema-per-guild-converted"

# The guild-content tables that existed in ``public`` at squash time (v0.53.5).
# Frozen: this guard reasons about the LEGACY snapshot, not about tables added
# later (which never get public copies).
_LEGACY_PUBLIC_GUILD_TABLES = (
    "calendar_event_attendees",
    "calendar_event_documents",
    "calendar_event_property_values",
    "calendar_event_tags",
    "calendar_events",
    "comments",
    "counter_groups",
    "counters",
    "document_file_versions",
    "document_links",
    "document_property_values",
    "document_tags",
    "documents",
    "event_reminder_dispatches",
    "guild_settings",
    "initiative_members",
    "initiative_role_permissions",
    "initiative_roles",
    "initiatives",
    "project_documents",
    "project_favorites",
    "project_orders",
    "project_tags",
    "projects",
    "property_definitions",
    "queue_item_documents",
    "queue_item_tags",
    "queue_item_tasks",
    "queue_items",
    "queues",
    "recent_views",
    "resource_grants",
    "subtasks",
    "tags",
    "task_assignees",
    "task_assignment_digest_items",
    "task_property_values",
    "task_statuses",
    "task_tags",
    "tasks",
    "uploads",
    "webhook_subscriptions",
)


def _assert_legacy_guilds_converted(conn) -> None:
    """Fail loudly if any guild still has unconverted rows in the frozen public
    copies. Fresh databases (no public copies) skip the whole check."""
    legacy_tables = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT c.table_name FROM information_schema.columns c "
                "WHERE c.table_schema = 'public' AND c.column_name = 'guild_id' "
                "AND c.table_name = ANY(:t)"
            ),
            {"t": list(_LEGACY_PUBLIC_GUILD_TABLES)},
        )
    ]
    if not legacy_tables:
        return  # fresh install — the public copies never existed

    guild_ids: set[int] = set()
    for table in legacy_tables:
        # ``table`` ∈ _LEGACY_PUBLIC_GUILD_TABLES (the catalog read above is
        # intersected with that hardcoded allowlist via ANY(:t)) — never user
        # input.
        rows = conn.execute(  # nosemgrep
            text(
                f'SELECT DISTINCT p.guild_id FROM public."{table}" p '  # noqa: S608
                "JOIN public.guilds g ON g.id = p.guild_id"
            )
        )
        guild_ids.update(r[0] for r in rows)

    unconverted = [
        gid
        for gid in sorted(guild_ids)
        if conn.execute(
            text(
                "SELECT obj_description(n.oid) FROM pg_namespace n WHERE n.nspname = :s"
            ),
            {"s": f"guild_{gid}"},
        ).scalar()
        != _CONVERSION_MARKER
    ]
    if unconverted:
        raise RuntimeError(
            "Cannot upgrade past the v0.53.5 squash: guild(s) "
            f"{unconverted} still have data in the legacy public tables but no "
            "completed schema-per-guild conversion. Deploy and boot a v0.53.x "
            "release once (its startup performs the conversion), then upgrade "
            "to this version."
        )


# --- 2. guild_template for deployments that skip the baseline ----------------


def _ensure_guild_template(conn) -> None:
    """Create guild_template from the frozen baseline snapshot when absent
    (legacy deployments skip the baseline, which creates it on fresh installs)."""
    exists = conn.execute(
        text(
            "SELECT 1 FROM information_schema.schemata "
            "WHERE schema_name = 'guild_template'"
        )
    ).scalar()
    if exists:
        return
    for statement in split_sql_statements(_TEMPLATE_SQL_PATH.read_text()):
        conn.execute(text(statement))


# --- 3. fleet healing (from the pre-release 0127) ----------------------------

# Orphans of the legacy per-resource permission tables (dropped by old 0116).
_DEAD_FUNCTIONS = (
    "fn_document_permissions_set_guild_id",
    "fn_project_permissions_set_guild_id",
)
_DEAD_ENUMS = (
    "counter_permission_level",
    "document_permission_level",
    "project_permission_level",
    "queue_permission_level",
)


def _heal_sequence_defaults(conn, schema: str) -> None:
    """Re-point column defaults that use a sequence outside ``schema`` to a
    schema-local sequence, without ever rewinding a sequence."""
    # pg_depend ties a column default (pg_attrdef) to the sequence its nextval
    # references — authoritative, no expression parsing. Schema names come from
    # pg_namespace and identifiers from the catalogs, so they're safe to quote.
    rows = conn.execute(
        text(
            """
            SELECT c.relname AS tbl, a.attname AS col,
                   sn.nspname AS seq_schema, s.relname AS seq
            FROM pg_attrdef ad
            JOIN pg_class c ON c.oid = ad.adrelid
            JOIN pg_namespace cn ON cn.oid = c.relnamespace AND cn.nspname = :schema
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ad.adnum
            JOIN pg_depend d ON d.classid = 'pg_attrdef'::regclass
                            AND d.objid = ad.oid
                            AND d.refclassid = 'pg_class'::regclass
            JOIN pg_class s ON s.oid = d.refobjid AND s.relkind = 'S'
            JOIN pg_namespace sn ON sn.oid = s.relnamespace
            WHERE sn.nspname <> :schema
            """
        ),
        {"schema": schema},
    ).fetchall()

    # tbl/col come from pg_catalog. Only the provisioner/migrations create
    # objects in guild schemas (guild roles hold USAGE + DML, no CREATE), so
    # these are our own snake_case names — but verify with an explicit
    # character allow-list before interpolating, so a hostile name could
    # never splice DDL even if that invariant ever slipped.
    ident_chars = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    for tbl, col, seq_schema, seq in rows:
        for ident in (tbl, col):
            if not ident or set(ident) - ident_chars:
                raise RuntimeError(
                    f"unexpected identifier in {schema} catalog: {ident!r}"
                )
        local_seq = f"{tbl}_{col}_seq"
        qseq = f'"{schema}"."{local_seq}"'
        conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {qseq} AS integer"))
        # Never rewind: advance to the max of the column's ids and wherever the
        # local sequence already is (it may exist and be live).
        conn.execute(  # nosemgrep
            text(
                f"SELECT setval('{qseq}', GREATEST("  # noqa: S608
                f'(SELECT COALESCE(max("{col}"), 0) FROM "{schema}"."{tbl}"), '
                f"(SELECT last_value FROM {qseq}), 1))"
            )
        )
        conn.execute(
            text(
                f'ALTER TABLE "{schema}"."{tbl}" ALTER COLUMN "{col}" '
                f"SET DEFAULT nextval('{qseq}'::regclass)"
            )
        )
        conn.execute(text(f'ALTER SEQUENCE {qseq} OWNED BY "{schema}"."{tbl}"."{col}"'))
        print(
            f"  healed {schema}.{tbl}.{col}: default was {seq_schema}.{seq}, "
            f"now {schema}.{local_seq}"
        )


def _drop_cross_schema_fks(conn, schema: str) -> None:
    """Drop FKs from ``schema``'s tables to the frozen public guild copies."""
    rows = conn.execute(
        text(
            """
            SELECT con.conname, cl.relname AS tbl
            FROM pg_constraint con
            JOIN pg_class cl ON cl.oid = con.conrelid
            JOIN pg_namespace cn ON cn.oid = cl.relnamespace AND cn.nspname = :schema
            JOIN pg_class tgt ON tgt.oid = con.confrelid
            JOIN pg_namespace tn ON tn.oid = tgt.relnamespace AND tn.nspname = 'public'
            WHERE con.contype = 'f' AND tgt.relname = ANY(:legacy)
            """
        ),
        {"schema": schema, "legacy": list(_LEGACY_PUBLIC_GUILD_TABLES)},
    ).fetchall()
    for conname, tbl in rows:
        conn.execute(
            text(f'ALTER TABLE "{schema}"."{tbl}" DROP CONSTRAINT "{conname}"')
        )
        print(f"  dropped cross-schema FK {schema}.{tbl}.{conname} -> public")


# --- 4. superadmin policy-leg removal (from the pre-release 0128) ------------

# NULLIF-guarded session-variable forms (see CLAUDE.md): an unset/empty GUC
# must compare as NULL, never raise mid-policy.
_GUILD_ID = "(NULLIF(current_setting('app.current_guild_id', true), ''))::integer"
_USER_ID = "(NULLIF(current_setting('app.current_user_id', true), ''))::integer"
_GUILD_ADMIN = "current_setting('app.current_guild_role', true) = 'admin'"
_SUPERADMIN_LEG = "current_setting('app.is_superadmin', true) = 'true'"

_INVITE_MEMBER = (
    "EXISTS (SELECT 1 FROM public.guild_memberships "
    "WHERE guild_memberships.guild_id = guild_invites.guild_id "
    f"AND guild_memberships.user_id = {_USER_ID})"
)
_GUILD_MEMBER = (
    "EXISTS (SELECT 1 FROM public.guild_memberships "
    "WHERE guild_memberships.guild_id = guilds.id "
    f"AND guild_memberships.user_id = {_USER_ID})"
)

# (table, policy, FOR clause, USING predicate | None, WITH CHECK predicate | None)
# — the predicates are the existing ones minus the dead superadmin leg.
_POLICIES: list[tuple[str, str, str, str | None, str | None]] = [
    ("guild_invites", "guild_select", "FOR SELECT", _INVITE_MEMBER, None),
    (
        "guild_invites",
        "guild_insert",
        "FOR INSERT",
        None,
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_invites",
        "guild_update",
        "FOR UPDATE",
        f"guild_id = {_GUILD_ID}",
        f"guild_id = {_GUILD_ID}",
    ),
    ("guild_invites", "guild_delete", "FOR DELETE", f"guild_id = {_GUILD_ID}", None),
    (
        "guilds",
        "guild_select",
        "FOR SELECT",
        f"id = {_GUILD_ID} OR {_GUILD_MEMBER}",
        None,
    ),
    ("guilds", "guild_insert", "FOR INSERT", None, f"{_USER_ID} IS NOT NULL"),
    (
        "guilds",
        "guild_update",
        "FOR UPDATE",
        f"id = {_GUILD_ID} AND {_GUILD_ADMIN}",
        f"id = {_GUILD_ID} AND {_GUILD_ADMIN}",
    ),
    (
        "guilds",
        "guild_delete",
        "FOR DELETE",
        f"id = {_GUILD_ID} AND {_GUILD_ADMIN}",
        None,
    ),
    (
        "oidc_claim_mappings",
        "guild_isolation",
        "",
        f"guild_id = {_GUILD_ID}",
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_memberships",
        "guild_memberships_select",
        "FOR SELECT",
        f"guild_id = {_GUILD_ID} OR user_id = {_USER_ID}",
        None,
    ),
    (
        "guild_memberships",
        "guild_memberships_insert",
        "FOR INSERT",
        None,
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_memberships",
        "guild_memberships_update",
        "FOR UPDATE",
        f"guild_id = {_GUILD_ID}",
        f"guild_id = {_GUILD_ID}",
    ),
    (
        "guild_memberships",
        "guild_memberships_delete",
        "FOR DELETE",
        f"guild_id = {_GUILD_ID}",
        None,
    ),
    (
        "user_view_preferences",
        "user_view_preferences_self_scope",
        "",
        f"user_id = {_USER_ID}",
        f"user_id = {_USER_ID}",
    ),
]


def _recreate(conn, superadmin_leg: bool) -> None:
    for table, policy, cmd, using, check in _POLICIES:
        conn.execute(text(f'DROP POLICY IF EXISTS "{policy}" ON public."{table}"'))
        parts = [f'CREATE POLICY "{policy}" ON public."{table}" {cmd}'.rstrip()]
        if using is not None:
            leg = f" OR ({_SUPERADMIN_LEG})" if superadmin_leg else ""
            parts.append(f"USING (({using}){leg})")
        if check is not None:
            leg = f" OR ({_SUPERADMIN_LEG})" if superadmin_leg else ""
            parts.append(f"WITH CHECK (({check}){leg})")
        conn.execute(text(" ".join(parts)))


# --- 5. grant matrices (from the pre-release 0129/0130) ----------------------

# table -> verbs the system engine's call sites use (audited).
_SYSTEM_TABLE_GRANTS: dict[str, str | None] = {
    "users": "SELECT, INSERT, UPDATE, DELETE",
    "guilds": "SELECT, INSERT, UPDATE, DELETE",
    "guild_memberships": "SELECT, INSERT, UPDATE, DELETE",
    # invite redemption reads/creates/updates; row removal rides the FK cascade
    "guild_invites": "SELECT, INSERT, UPDATE",
    "access_grants": "SELECT, INSERT, UPDATE, DELETE",
    # singleton config: seeded + updated, never deleted
    "app_settings": "SELECT, INSERT, UPDATE",
    # OIDC sync reads mappings; the settings endpoints manage them (system engine)
    "oidc_claim_mappings": "SELECT, INSERT, UPDATE, DELETE",
    # personal UI state — the system engine has no business here
    "user_view_preferences": None,
    "notifications": "SELECT, INSERT, DELETE",
    "user_tokens": "SELECT, INSERT, DELETE",
    "push_tokens": "SELECT, INSERT, DELETE",
    "user_api_keys": "SELECT, DELETE",
    "auto_delegation_jti_blocklist": "SELECT, INSERT",
    # migrations-only bookkeeping (the provisioning role owns it)
    "alembic_version": None,
}


# table -> verbs the bare login role's audited call sites use.
_APP_USER_TABLE_GRANTS: dict[str, str | None] = {
    "users": "SELECT, UPDATE",
    "user_tokens": "SELECT, INSERT, UPDATE, DELETE",
    "user_api_keys": "SELECT, INSERT, UPDATE, DELETE",
    "auto_delegation_jti_blocklist": "SELECT, INSERT",
    "app_settings": "SELECT",
    "guilds": "SELECT",
    "guild_invites": "SELECT",
    "guild_memberships": "SELECT",
    "access_grants": "SELECT",
    "notifications": None,
    "oidc_claim_mappings": None,
    "push_tokens": None,
    "user_view_preferences": None,
    "alembic_version": None,
}


def _apply_grant_matrices(conn) -> None:
    for role, matrix in (
        ("app_admin", _SYSTEM_TABLE_GRANTS),
        ("app_user", _APP_USER_TABLE_GRANTS),
    ):
        for table, verbs in matrix.items():
            conn.execute(text(f'REVOKE ALL ON TABLE public."{table}" FROM {role}'))
            if verbs:
                conn.execute(text(f'GRANT {verbs} ON TABLE public."{table}" TO {role}'))
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"REVOKE ALL ON TABLES FROM {role}"
            )
        )
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"REVOKE ALL ON SEQUENCES FROM {role}"
            )
        )


def upgrade() -> None:
    conn = op.get_bind()
    _assert_legacy_guilds_converted(conn)
    _ensure_guild_template(conn)
    for schema in guild_schema_names(conn):
        _heal_sequence_defaults(conn, schema)
        _drop_cross_schema_fks(conn, schema)
    for fn in _DEAD_FUNCTIONS:
        conn.execute(text(f"DROP FUNCTION IF EXISTS public.{fn}()"))
    for enum in _DEAD_ENUMS:
        conn.execute(text(f"DROP TYPE IF EXISTS public.{enum}"))
    _recreate(conn, superadmin_leg=False)
    _apply_grant_matrices(conn)


def downgrade() -> None:
    raise NotImplementedError(
        "20260702_0126 reconciles pre-collapse states; roll forward only."
    )
