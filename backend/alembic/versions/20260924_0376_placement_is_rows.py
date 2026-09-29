"""placement is rows

Where an installed app appears was a JSONB column on ``guild_apps``: ``{}`` for
every initiative, ``{"initiatives": [ids]}`` for only those, ``{"initiatives":
[]}`` for none. It becomes ``app_placements``, one row per (install,
initiative), carrying the initiative roles allowed to open the app there.

Every existing placement becomes rows: ``{}`` one per initiative that exists
now, a list one per listed initiative that still exists, ``[]`` none. Each row
takes that initiative's built-in moderator role.

A mandatory install is placed in each initiative created after it. That is
``guild_apps.follows_new_initiatives``, set here for the installs whose listing
a registration marks mandatory, and a trigger on ``initiative_roles`` that adds
the row when an initiative's built-in moderator role is created.

``app_placements`` gets its policies from the registry at boot, like every
guild table; this revision writes none.

Revision ID: 20260924_0376
Revises: 20260924_0375
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0376"
down_revision = "20260924_0375"
branch_labels = None
depends_on = None


#: Shared, in ``public``, created once; each guild schema attaches a trigger to
#: it. The schema is the one the trigger fired in, so a row lands beside the
#: role that caused it whatever the caller's search_path.
_PLACE_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_place_following_apps() RETURNS trigger
    LANGUAGE plpgsql AS $place$
BEGIN
    IF NEW.is_builtin AND NEW.name = 'moderator' THEN
        EXECUTE format(
            'INSERT INTO %I.app_placements '
            '(install_id, initiative_id, role_ids, created_at, updated_at) '
            'SELECT a.id, $1, ARRAY[$2]::integer[], now(), now() '
            'FROM %I.guild_apps a WHERE a.follows_new_initiatives '
            'ON CONFLICT DO NOTHING',
            TG_TABLE_SCHEMA, TG_TABLE_SCHEMA
        ) USING NEW.initiative_id, NEW.id;
    END IF;
    RETURN NULL;
END;
$place$;
"""

_TRIGGER = "tr_initiative_roles_place_following_apps"


def _forced(bind, table: str) -> bool:
    """Whether ``table`` currently forces RLS on its owner."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )


def _mandatory_listing_uids(bind) -> list[str]:
    """The listings a registration marks mandatory."""
    table = "public.app_service_registrations"
    forced = _forced(bind, table)
    if forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        return list(
            bind.execute(
                sa.text(
                    "SELECT listing_uid FROM public.app_service_registrations "
                    "WHERE mandatory AND listing_uid IS NOT NULL"
                )
            ).scalars()
        )
    finally:
        if forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    mandatory = _mandatory_listing_uids(bind)
    op.execute(_PLACE_FUNCTION)
    run_for_each_guild_schema(bind, lambda: _apply_upgrade(bind, mandatory))


def _apply_upgrade(bind, mandatory: list[str]) -> None:
    op.create_table(
        "app_placements",
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column(
            "role_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["install_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("install_id", "initiative_id"),
    )
    op.create_index(
        "ix_app_placements_initiative_id", "app_placements", ["initiative_id"]
    )

    _backfill_placements(bind)

    op.add_column(
        "guild_apps",
        sa.Column(
            "follows_new_initiatives",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    if mandatory:
        bind.execute(
            sa.text(
                "UPDATE guild_apps SET follows_new_initiatives = true "
                "WHERE listing_uid = ANY(:uids)"
            ).bindparams(sa.bindparam("uids", type_=postgresql.ARRAY(sa.String()))),
            {"uids": mandatory},
        )

    op.drop_column("guild_apps", "placement")

    op.execute(
        f"CREATE OR REPLACE TRIGGER {_TRIGGER} "
        "AFTER INSERT ON initiative_roles "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_place_following_apps()"
    )


def _backfill_placements(bind) -> None:
    """One row per (install, initiative) the stored placement named, trashed
    initiatives included, so a restored initiative keeps its placement."""
    forced = _forced(bind, "initiatives")
    if forced:
        op.execute("ALTER TABLE initiatives NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            """
            INSERT INTO app_placements
                (install_id, initiative_id, role_ids, created_at, updated_at)
            SELECT a.id, i.id,
                   COALESCE(
                       (SELECT ARRAY[r.id] FROM initiative_roles r
                         WHERE r.initiative_id = i.id
                           AND r.name = 'moderator'
                           AND r.is_builtin
                         ORDER BY r.id LIMIT 1),
                       '{}'::integer[]),
                   now(), now()
            FROM guild_apps a
            JOIN initiatives i ON (
                jsonb_typeof(a.placement) IS DISTINCT FROM 'object'
                OR jsonb_typeof(a.placement -> 'initiatives')
                   IS DISTINCT FROM 'array'
                OR (a.placement -> 'initiatives') @> to_jsonb(i.id)
            )
            ON CONFLICT DO NOTHING
            """
        )
    finally:
        if forced:
            op.execute("ALTER TABLE initiatives FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    # Reachable only from the triggers just dropped.
    op.execute("DROP FUNCTION IF EXISTS public.fn_place_following_apps()")


def _apply_downgrade() -> None:
    op.add_column(
        "guild_apps",
        sa.Column(
            "placement",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    # Each install names the initiatives it is placed in; one placed nowhere
    # names none, which the earlier shape reads as placed nowhere.
    op.execute(
        """
        UPDATE guild_apps a SET placement = jsonb_build_object(
            'initiatives',
            COALESCE(
                (SELECT jsonb_agg(p.initiative_id ORDER BY p.initiative_id)
                   FROM app_placements p WHERE p.install_id = a.id),
                '[]'::jsonb))
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON initiative_roles")
    op.drop_column("guild_apps", "follows_new_initiatives")
    op.drop_index("ix_app_placements_initiative_id", table_name="app_placements")
    op.drop_table("app_placements")
