"""moderator becomes a built-in role, and carries Full access

"Full access" — ``initiative_roles.override_share_restrictions``, the right to
open and edit every item in an initiative however each one is shared, and to
manage that sharing — used to be a switch a community admin could throw on an
initiative's project manager role. It is now what one role *is*: every
initiative gains a built-in ``moderator``, listed first, holding every tool
permission and Full access. The project manager keeps its tool permissions and
loses the switch.

Guild content, so this walks every ``guild_<id>``. ``guild_template`` holds no
initiatives, so nothing here has anything to say to it; the structure of the
table is unchanged.

Two sets of memberships move onto the new role: whoever held Full access through
a project manager role that had the switch on, so nobody's reach narrows on
upgrade, and everyone whose community role is admin, which is where every route
into an initiative now puts them. The count of roles created is asserted against
the count of initiatives that lacked one: a fresh install has no initiatives at
all, so a silent zero would look exactly like success.

An initiative that already had a role named ``moderator`` of its own keeps it
under the first free name of ``moderator_<id>``, ``moderator_<id>_1``, … — the
name is per-initiative unique, and the built-in needs it. The display name it is
known by is untouched, so nobody sees the difference. The downgrade does not
undo that rename: nothing records which role gave the name up, and a guess can
land on a role that was always called that.

Revision ID: 20260913_0265
Revises: 20260913_0264
Create Date: 2026-09-13
"""

import logging

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260913_0265"
down_revision = "20260913_0264"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


#: The candidate names a role giving up ``moderator`` is offered, in order:
#: ``moderator_<its id>``, then that with ``_1``, ``_2`` … appended. The id
#: alone is almost always free — a name is unique per initiative, and that one
#: is not a name anybody types — but "almost always" is not a thing to write
#: into an upgrade, so the numbered ones are there and the first free one wins.
_CANDIDATE_NAME = (
    "'moderator_' || victim.id || CASE WHEN g.n = 0 THEN '' ELSE '_' || g.n END"
)

#: Give up the name to the built-in, which needs it.
_FREE_THE_NAME = f"""
    UPDATE initiative_roles victim
       SET name = (
               SELECT {_CANDIDATE_NAME}
                 FROM generate_series(0, 99) AS g(n)
                WHERE NOT EXISTS (
                          SELECT 1
                            FROM initiative_roles other
                           WHERE other.initiative_id = victim.initiative_id
                             AND other.name = {_CANDIDATE_NAME}
                      )
                ORDER BY g.n
                LIMIT 1
           )
     WHERE victim.name = 'moderator' AND NOT victim.is_builtin
"""

#: The initiatives the new role is about to be inserted into.
_LACKING = """
    SELECT i.id
      FROM initiatives i
     WHERE NOT EXISTS (
               SELECT 1 FROM initiative_roles r
                WHERE r.initiative_id = i.id AND r.name = 'moderator'
           )
"""

#: Moderator lists first, so everything already there moves down one.
_MAKE_ROOM = f"""
    UPDATE initiative_roles
       SET "position" = "position" + 1
     WHERE initiative_id IN ({_LACKING})
"""

_CLOSE_THE_GAP = """
    UPDATE initiative_roles
       SET "position" = "position" - 1
     WHERE "position" > 0
"""

_CREATE_ROLE = f"""
    INSERT INTO initiative_roles (
        initiative_id, name, display_name, is_builtin, is_manager,
        override_share_restrictions, "position"
    )
    SELECT id, 'moderator', 'Moderator', true, true, true, 0
      FROM ({_LACKING}) AS lacking
"""

#: Every permission key, at true. Read off the initiative's project manager —
#: which holds them all — rather than written out here, so this says "the same
#: tools the project manager has" in whatever database it runs in.
_GRANT_EVERY_TOOL = """
    INSERT INTO initiative_role_permissions (
        initiative_role_id, permission_key, enabled
    )
    SELECT moderator.id, pm_perm.permission_key, true
      FROM initiative_roles moderator
      JOIN initiative_roles pm
        ON pm.initiative_id = moderator.initiative_id
       AND pm.name = 'project_manager'
      JOIN initiative_role_permissions pm_perm
        ON pm_perm.initiative_role_id = pm.id
     WHERE moderator.name = 'moderator' AND moderator.is_builtin
"""

#: Whoever held Full access through the project manager role keeps it, on the
#: role that carries it now. Runs before the switch below is cleared, which is
#: the only record of which initiatives had it on.
_FULL_ACCESS_PMS_BECOME_MODERATORS = """
    UPDATE initiative_members im
       SET role_id = moderator.id
      FROM initiative_roles pm
      JOIN initiative_roles moderator
        ON moderator.initiative_id = pm.initiative_id
       AND moderator.name = 'moderator'
       AND moderator.is_builtin
     WHERE pm.id = im.role_id
       AND pm.name = 'project_manager'
       AND pm.is_builtin
       AND pm.override_share_restrictions
"""

_PM_KEEPS_ITS_TOOLS_ONLY = """
    UPDATE initiative_roles
       SET override_share_restrictions = false
     WHERE name = 'project_manager' AND is_builtin
"""

#: A community admin's row carries the moderator role wherever they are already
#: a member, matching what every route into an initiative now writes.
_ADMINS_BECOME_MODERATORS = """
    UPDATE initiative_members im
       SET role_id = moderator.id
      FROM initiative_roles moderator
     WHERE moderator.initiative_id = im.initiative_id
       AND moderator.name = 'moderator'
       AND moderator.is_builtin
       AND im.role_id IS DISTINCT FROM moderator.id
       AND EXISTS (
               SELECT 1
                 FROM public.guild_memberships gm
                WHERE gm.guild_id = im.guild_id
                  AND gm.user_id = im.user_id
                  AND gm.role = 'admin'
           )
"""

#: Reverse of the above: whoever is on the moderator role goes back to the
#: project manager, the role that used to hold Full access.
_MODERATORS_BECOME_PROJECT_MANAGERS = """
    UPDATE initiative_members im
       SET role_id = pm.id
      FROM initiative_roles moderator
      JOIN initiative_roles pm
        ON pm.initiative_id = moderator.initiative_id
       AND pm.name = 'project_manager'
     WHERE moderator.id = im.role_id
       AND moderator.name = 'moderator'
       AND moderator.is_builtin
"""

#: An initiative whose moderator role held a member who is not a community
#: admin had somebody with Full access the older shape can only say one way: the
#: switch on its project manager. A moderator who IS a community admin is
#: excluded — their access comes from their community standing, and turning the
#: switch on for them would hand Full access to every project manager there too.
_PM_TAKES_FULL_ACCESS_BACK = """
    UPDATE initiative_roles pm
       SET override_share_restrictions = true
     WHERE pm.name = 'project_manager'
       AND pm.is_builtin
       AND EXISTS (
               SELECT 1
                 FROM initiative_roles moderator
                 JOIN initiative_members im ON im.role_id = moderator.id
                WHERE moderator.initiative_id = pm.initiative_id
                  AND moderator.name = 'moderator'
                  AND moderator.is_builtin
                  AND NOT EXISTS (
                          SELECT 1
                            FROM public.guild_memberships gm
                           WHERE gm.guild_id = im.guild_id
                             AND gm.user_id = im.user_id
                             AND gm.role = 'admin'
                      )
           )
"""

_DROP_ROLE = """
    DELETE FROM initiative_roles
     WHERE name = 'moderator' AND is_builtin
"""


def _route(connection, schema: str) -> None:
    connection.execute(
        sa.text("SELECT set_config('search_path', :sp, true)"),
        {"sp": f'"{schema}", public'},
    )


def apply_to_routed_schema(connection, label: str) -> tuple[int, int]:
    """Do the whole change in whatever schema the connection is routed to.

    Returns (roles created, memberships moved). ``label`` names the schema in
    the error if the count of roles created does not match the count of
    initiatives that needed one. Public so a test can run this against a schema
    holding the shape a real upgrade meets, which the migration's own loop never
    sees on a fresh install.
    """
    connection.execute(sa.text(_FREE_THE_NAME))
    expected = connection.execute(
        sa.text(f"SELECT count(*) FROM ({_LACKING}) lacking")
    ).scalar_one()
    connection.execute(sa.text(_MAKE_ROOM))
    created = connection.execute(sa.text(_CREATE_ROLE)).rowcount
    if created != expected:
        raise RuntimeError(
            f"{label}: {expected} initiative(s) needed a moderator role but "
            f"{created} were created"
        )
    connection.execute(sa.text(_GRANT_EVERY_TOOL))
    moved = connection.execute(sa.text(_FULL_ACCESS_PMS_BECOME_MODERATORS)).rowcount
    connection.execute(sa.text(_PM_KEEPS_ITS_TOOLS_ONLY))
    moved += connection.execute(sa.text(_ADMINS_BECOME_MODERATORS)).rowcount
    return created, moved


def revert_in_routed_schema(connection) -> None:
    """The reverse, in whatever schema the connection is routed to."""
    connection.execute(sa.text(_PM_TAKES_FULL_ACCESS_BACK))
    connection.execute(sa.text(_MODERATORS_BECOME_PROJECT_MANAGERS))
    connection.execute(sa.text(_DROP_ROLE))
    connection.execute(sa.text(_CLOSE_THE_GAP))


def upgrade() -> None:
    connection = op.get_bind()
    roles_created = 0
    admins_moved = 0

    for schema in guild_schema_names(connection):
        _route(connection, schema)
        created, moved = apply_to_routed_schema(connection, schema)
        roles_created += created
        admins_moved += moved

    connection.execute(sa.text("SET LOCAL search_path = public"))
    logger.info(
        "moderator role created in %s initiative(s); %s community-admin "
        "membership(s) moved onto it",
        roles_created,
        admins_moved,
    )


def downgrade() -> None:
    connection = op.get_bind()

    for schema in guild_schema_names(connection):
        _route(connection, schema)
        revert_in_routed_schema(connection)

    connection.execute(sa.text("SET LOCAL search_path = public"))
