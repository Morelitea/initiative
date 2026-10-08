"""An account has no name

``public.users.full_name`` goes. Outside a community a person is their handle;
inside one, the name they or its administrators set there
(``guild_memberships.display_name``, 0438). With it goes the guild's
``show_member_names``, which 0438 already stopped consulting, together with
its CHECK and its column grant (both dropped with the column), and the reader's
read of ``public.guilds`` that existed only to consult it.

The guild projection's name column is renamed ``display_name`` to say what it
holds. A view cannot rename a column in place, and ``current_guild_members``
is built on ``guild_member_profiles``, so both are dropped and rebuilt. Their
privileges are carried across from the catalog rather than restated: besides
the floors, every guild's query role holds a grant on the members view, and
those roles exist only at runtime.

The names are not recoverable. The downgrade restores the columns, empty, and
0438's views.

Revision ID: 20261002_0439
Revises: 20261002_0438
Create Date: 2026-10-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20261002_0439"
down_revision = "20261002_0438"
branch_labels = None
depends_on = None

#: The reader role that owns both projections. Created in 0214.
READER = "app_profile_reader"

PROFILES = "public.guild_member_profiles"
MEMBERS = "public.current_guild_members"

#: The policy 0281 gave the reader to consult ``show_member_names``.
NAME_RULE_POLICY = "profile_reader_reads_the_name_rule"

#: The guild the request is routed into, as 0281 reads it.
ROUTED_GUILD_ID = """COALESCE(
        NULLIF(current_setting('app.current_guild_id', true), '')::int,
        NULLIF(current_setting('app.pam_guild_id', true), '')::int
    )"""

#: Written out rather than imported so a replay of this revision builds the
#: views this revision built.
BEFORE = ("id", "username", "discriminator")
AFTER = ("avatar_url", "status", "custom_status", "profile_decorations", "created_at")

#: 0386's install rule, unchanged.
INSTALL_READS_ITS_MEMBERS = f"""
    NULLIF(current_setting('app.current_install_id', true), '') IS NULL
    OR u.id IN (
        SELECT gm.user_id FROM public.guild_memberships gm
        WHERE gm.guild_id = {ROUTED_GUILD_ID}
    )"""


def _profiles(name_column: str) -> str:
    columns = ", ".join(
        (
            *(f"u.{c}" for c in BEFORE),
            f"m.display_name::varchar AS {name_column}",
            *(f"u.{c}" for c in AFTER),
        )
    )
    return f"""
CREATE VIEW {PROFILES} AS
SELECT {columns}
FROM public.users u
LEFT JOIN public.guild_memberships m
    ON m.user_id = u.id AND m.guild_id = {ROUTED_GUILD_ID}
WHERE {INSTALL_READS_ITS_MEMBERS}"""


def _members(name_column: str) -> str:
    """0244's view over the projection: the routed guild's members, and the
    name to group by — theirs where they set one, the handle where not."""
    # 0244 carried the raw name beside the grouping one; under its new name
    # the grouping column is the only one.
    carried = () if name_column == "display_name" else (name_column,)
    columns = ", ".join(f"p.{c}" for c in (*BEFORE, *carried, *AFTER))
    return f"""
CREATE VIEW {MEMBERS} AS
SELECT {columns}, COALESCE(p.{name_column}, p.username) AS display_name
FROM {PROFILES} p
JOIN public.guild_memberships m ON m.user_id = p.id
WHERE m.guild_id = {ROUTED_GUILD_ID}"""


def _privileges(view: str) -> list[tuple[str, str]]:
    """Who holds what on ``view`` besides its owner, as GRANT can spell it."""
    rows = op.get_bind().execute(
        sa.text(
            """
            SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC'
                        ELSE quote_ident(r.rolname) END,
                   a.privilege_type
            FROM pg_class c
            CROSS JOIN LATERAL aclexplode(c.relacl) a
            LEFT JOIN pg_roles r ON r.oid = a.grantee
            WHERE c.oid = to_regclass(:view) AND a.grantee <> c.relowner
            """
        ),
        {"view": view},
    )
    return [(grantee, privilege) for grantee, privilege in rows]


def _rebuild(name_column: str) -> None:
    """Drop and recreate both views with ``name_column``, keeping who may read
    them exactly as it was."""
    held = {view: _privileges(view) for view in (PROFILES, MEMBERS)}
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(f"DROP VIEW {MEMBERS}")
    op.execute(f"DROP VIEW {PROFILES}")
    op.execute(_profiles(name_column))
    op.execute(_members(name_column))
    # Ownership can only be handed to a role that may create in the schema;
    # given for the assignment and taken straight back, as 0220 and 0244 do.
    op.execute(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    for view, privileges in held.items():
        op.execute(f'ALTER VIEW {view} OWNER TO "{READER}"')
        # A new relation picks up the schema's default privileges; what the
        # old one held is the whole of what the new one holds.
        for grantee, privilege in _privileges(view):
            op.execute(f"REVOKE {privilege} ON {view} FROM {grantee}")
        for grantee, privilege in privileges:
            op.execute(f"GRANT {privilege} ON {view} TO {grantee}")
    op.execute(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')


def upgrade() -> None:
    _rebuild("display_name")
    op.execute(f"DROP POLICY IF EXISTS {NAME_RULE_POLICY} ON public.guilds")
    op.execute(
        f'REVOKE SELECT (id, show_member_names) ON public.guilds FROM "{READER}"'
    )
    op.execute("ALTER TABLE public.guilds DROP COLUMN show_member_names")
    op.execute("ALTER TABLE public.users DROP COLUMN full_name")


def downgrade() -> None:
    op.execute("ALTER TABLE public.users ADD COLUMN full_name varchar")
    op.execute(
        "ALTER TABLE public.guilds ADD COLUMN show_member_names boolean "
        "NOT NULL DEFAULT true"
    )
    op.execute("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("UPDATE public.guilds SET show_member_names = NOT is_community")
    finally:
        op.execute("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")
    op.execute(
        "ALTER TABLE public.guilds ADD CONSTRAINT ck_guilds_community_member_names "
        "CHECK (NOT (is_community AND show_member_names))"
    )
    op.execute(
        "GRANT UPDATE (show_member_names) ON TABLE public.guilds TO app_guild_base"
    )
    op.execute(f'GRANT SELECT (full_name) ON TABLE public.users TO "{READER}"')
    op.execute(f'GRANT SELECT (id, show_member_names) ON public.guilds TO "{READER}"')
    op.execute(
        f"CREATE POLICY {NAME_RULE_POLICY} ON public.guilds "
        f'FOR SELECT TO "{READER}" USING (true)'
    )
    _rebuild("full_name")
