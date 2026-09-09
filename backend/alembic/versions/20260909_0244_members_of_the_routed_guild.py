"""Publish the members of the guild a request is routed into

``public.guild_member_profiles`` (0220) projects an account for *any* id: a
person is a person wherever they are looked up, which is what the cross-guild
profile page needs and what every name a guild renders is read through.

That is the wrong shape for a surface somebody writes queries against. A
statement names a relation and gets its rows, so a relation over every account
on the deployment would be one every guild could list. This adds the guild's
own view of the same projection — its members, and nobody else's — for the
query surface to name.

Which guild is not a parameter: it is the one the request is already routed
into, read from the same context every policy reads. Unset, the join matches
nothing, so an unrouted session gets no rows rather than all of them.

Reading it does not depend on the caller's own view of the membership table,
because that view is not the same question. ``guild_memberships`` answers "the
guild you are in, or your own row", and a grantee is in neither — they hold a
grant instead, which is what routes them. So the projection reads it as the
role that owns it, under a policy of its own that permits exactly the routed
guild, and the view's own filter says the same thing. One rule, in two places
that cannot disagree.

Revision ID: 20260909_0244
Revises: 20260909_0243
Create Date: 2026-09-09
"""

from alembic import op

revision = "20260909_0244"
down_revision = "20260909_0243"
branch_labels = None
depends_on = None

VIEW = "public.current_guild_members"

#: The guild this request is in. A grantee routes by the grant instead, and
#: NULLIF-guards the cast so an unset context yields NULL rather than faulting.
_GUILD = (
    "COALESCE("
    "NULLIF(current_setting('app.current_guild_id', true), '')::integer, "
    "NULLIF(current_setting('app.pam_guild_id', true), '')::integer)"
)

#: What the guild projection carries, in its own order — the same columns
#: ``GUILD_MEMBER_PROFILE_COLUMNS`` names. Written out rather than imported so a
#: replay of this revision builds the view this revision built.
COLUMNS = (
    "id",
    "username",
    "discriminator",
    "full_name",
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)

#: One column to group by and one to label with. A guild that does not render
#: real names has no ``full_name`` to give (0243), and the handle is what is
#: left — so the fallback is where the name would have been rather than a
#: second thing for a query to choose between.
DISPLAY_NAME = "COALESCE(p.full_name, p.username) AS display_name"

#: The floors every guild role reads shared relations through. Both, because
#: they are kept as one set: the read-only floor holds what the writable one
#: can read and nothing else.
FLOORS = ("app_guild_base", "app_guild_base_ro")

#: The public/platform floor, which this is not for. A request with no guild
#: gets no rows from it anyway; taking the privilege away says the same thing
#: where the catalog can be asked.
PLATFORM_FLOOR = "platform_base"

#: The role that owns both projections of an account. Created in 0214.
READER = "app_profile_reader"

#: What the projection may see of the membership table: the rows of the guild
#: the request is routed into, and nothing else. Narrow, and scoped to the one
#: NOLOGIN role that reads it, so no other consumer of the table gains a thing.
MEMBERSHIP_POLICY = "guild_membership_projection_read"


def _view() -> str:
    projected = ", ".join(f"p.{column}" for column in COLUMNS)
    return f"""
CREATE VIEW {VIEW} AS
SELECT {projected}, {DISPLAY_NAME}
FROM public.guild_member_profiles p
JOIN public.guild_memberships m ON m.user_id = p.id
WHERE m.guild_id = {_GUILD}
"""


def upgrade() -> None:
    # Owning the view means being able to create it. The reader already owns
    # the projection underneath.
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(
        f'GRANT SELECT (guild_id, user_id) ON public.guild_memberships TO "{READER}"'
    )
    op.execute(
        f"""
        CREATE POLICY {MEMBERSHIP_POLICY} ON public.guild_memberships
        FOR SELECT TO "{READER}"
        USING (guild_id = {_GUILD})
        """
    )
    op.execute(_view())
    # Ownership can only be handed to a role that may create in the schema.
    # Given for the assignment and taken straight back: the reader creates
    # nothing, it only reads (the same dance 0220 does).
    op.execute(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    op.execute(f'ALTER VIEW {VIEW} OWNER TO "{READER}"')
    op.execute(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')
    for floor in FLOORS:
        # The schema's default privileges hand every new relation in ``public``
        # full DML to these, so the read is granted and the rest taken back.
        # Nothing here is writable in any case — a join is not an updatable
        # view — but the privilege is what the catalog is asked about.
        op.execute(f'GRANT SELECT ON {VIEW} TO "{floor}"')
        op.execute(f'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {VIEW} FROM "{floor}"')
    op.execute(f'REVOKE ALL ON {VIEW} FROM "{PLATFORM_FLOOR}"')


def downgrade() -> None:
    op.execute(f'GRANT "{READER}" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE')
    op.execute(f"DROP VIEW IF EXISTS {VIEW}")
    op.execute(f"DROP POLICY IF EXISTS {MEMBERSHIP_POLICY} ON public.guild_memberships")
    op.execute(
        f'REVOKE SELECT (guild_id, user_id) ON public.guild_memberships FROM "{READER}"'
    )
