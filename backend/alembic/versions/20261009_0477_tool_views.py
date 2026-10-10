"""tool views

``tool_views``, in every guild schema: an initiative's views of a tool and its
item layouts, for one instance of the tool (``tool``, ``tool_id``) or, for a
tool whose page the initiative shares, the initiative itself (``tool_id``
NULL). Its policies, change capture and freeze are rendered by the
provisioning run.

A project's filter presets become its views, storing only what someone made.
A project whose presets are the four it was seeded with (All, Incomplete,
Unassigned, Mine), untouched, with All the default and no other default view
mode, stores nothing: the shipped views (Table, Board, Calendar, Incomplete,
Unassigned, Mine) are the same. Any other project stores the shipped six with
its changes: a seed it deleted is left out, a seed it edited takes the shipped
view of its slug, and each other preset follows as a view with the project's
default layout. All as seeded is the shipped Table, so it becomes no view;
renamed or refiltered, it is one more preset. The default is the default
preset's view, or, where that was All as seeded, the layout view of the
project's default view mode. A preset keeps its slug; where it holds
``table``, ``board`` or ``calendar``, the shipped layout view is suffixed.
``project_filter_presets`` goes; ``projects.default_view_mode`` goes in the
next revision.

The downgrade puts the presets back: one for each of a project's views that
holds filters and nothing else, and the four seeds for a project that stored
no views.

Revision ID: 20261009_0477
Revises: 20261009_0476
Create Date: 2026-10-09
"""

import json
from typing import Any, Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261009_0477"
down_revision = "20261009_0476"
branch_labels = None
depends_on = None

#: The presets a project was seeded with, as they stood at this revision:
#: slug -> (name, filters). ``all`` was the default.
_SEEDS: dict[str, tuple[str, dict[str, Any]]] = {
    "all": ("All", {}),
    "incomplete": (
        "Incomplete",
        {"status_categories": ["backlog", "todo", "in_progress"]},
    ),
    "unassigned": ("Unassigned", {"assignees": ["none"]}),
    "mine": ("Mine", {"assignees": ["me"]}),
}
#: The views a project ships, as they stood at this revision: (slug, name,
#: layout, filters).
_SHIPPED: tuple[tuple[str, str, str, Optional[dict[str, Any]]], ...] = (
    ("table", "Table", "table", None),
    ("board", "Board", "board", None),
    ("calendar", "Calendar", "calendar", None),
    ("incomplete", "Incomplete", "table", _SEEDS["incomplete"][1]),
    ("unassigned", "Unassigned", "table", _SEEDS["unassigned"][1]),
    ("mine", "Mine", "table", _SEEDS["mine"][1]),
)
#: ``default_view_mode`` -> the layout it named.
_MODE_LAYOUT = {"table": "table", "kanban": "board", "calendar": "calendar"}
_SLUG_LENGTH = 64
_TARGET = ["initiative_id", "tool", "tool_id"]


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "tool_views",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=32), nullable=False),
        sa.Column("tool_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("item_kind", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "tool IN ('project', 'queue', 'counter_group', 'gallery', "
            "'calendar', 'post')",
            name="ck_tool_views_tool",
        ),
        sa.CheckConstraint(
            "(tool IN ('calendar', 'post')) = (tool_id IS NULL)",
            name="ck_tool_views_target",
        ),
        sa.CheckConstraint(
            "(kind = 'view' AND name IS NOT NULL AND slug IS NOT NULL"
            " AND item_kind IS NULL)"
            " OR (kind = 'item_layout' AND item_kind IS NOT NULL)",
            name="ck_tool_views_kind",
        ),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_views_initiative_id", "tool_views", ["initiative_id"])
    op.create_index(
        "uq_tool_views_slug",
        "tool_views",
        [*_TARGET, "slug"],
        unique=True,
        postgresql_where=sa.text("kind = 'view'"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_tool_views_item_layout",
        "tool_views",
        [*_TARGET, "item_kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'item_layout'"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_tool_views_one_default",
        "tool_views",
        _TARGET,
        unique=True,
        postgresql_where=sa.text("kind = 'view' AND is_default"),
        postgresql_nulls_not_distinct=True,
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER tr_tool_views_set_created_by "
        "BEFORE INSERT ON tool_views "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )

    # Filled before the provisioning run gives it row security; the tables it
    # is filled from are read with theirs lifted.
    _lifted(("projects", "project_filter_presets"), _presets_to_views)

    op.drop_table("project_filter_presets")


def _lifted(tables: tuple[str, ...], fn: Any) -> None:
    """Run ``fn`` with row security lifted on ``tables``, restoring it either
    way. ``guild_template`` carries no row security, so only what was set is
    put back."""
    forced = [
        table
        for table in tables
        if op.get_bind()
        .execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        )
        .scalar()
    ]
    for table in forced:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        fn()
    finally:
        for table in forced:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _suffixed(slug: str, taken: set[str]) -> str:
    candidate, suffix = slug, 2
    while candidate in taken:
        room = _SLUG_LENGTH - len(str(suffix)) - 1
        candidate = f"{slug[:room].strip('-')}-{suffix}"
        suffix += 1
    return candidate


def _untouched(project: Any, presets: list[Any]) -> bool:
    """Whether a project is as it was seeded: the four seeds unchanged, All the
    default, and no default view mode other than the table."""
    return (
        project.default_view_mode in (None, "table")
        and len(presets) == len(_SEEDS)
        and all(
            _SEEDS.get(preset.slug) == (preset.name, preset.filters)
            and preset.is_default == (preset.slug == "all")
            for preset in presets
        )
    )


def _project_views(project: Any, presets: list[Any]) -> list[dict[str, Any]]:
    """The views a project stores: the shipped six with its changes, then
    its other presets, a changed All among them."""
    layout = _MODE_LAYOUT.get(project.default_view_mode or "", "table")
    own = {preset.slug: preset for preset in presets}
    # All as seeded is the shipped Table; changed, it is a view of its own.
    custom = [
        preset
        for preset in presets
        if preset.slug not in _SEEDS
        or (preset.slug == "all" and _SEEDS["all"] != (preset.name, preset.filters))
    ]
    taken = {preset.slug for preset in custom}

    def view(
        slug: str, name: str, view_layout: str, filters: Any, preset: Any = None
    ) -> dict[str, Any]:
        definition: dict[str, Any] = {"layout": {"type": view_layout}}
        if filters is not None:
            definition["filters"] = filters
        return {
            "slug": slug,
            "name": name,
            "definition": definition,
            "is_default": bool(preset is not None and preset.is_default),
            "created_by": preset.created_by if preset is not None else None,
            "created_at": preset.created_at if preset is not None else None,
            "updated_at": preset.updated_at if preset is not None else None,
        }

    views: list[dict[str, Any]] = []
    layout_views: dict[str, dict[str, Any]] = {}
    for slug, name, view_layout, filters in _SHIPPED:
        if filters is None:
            shipped = view(_suffixed(slug, taken), name, view_layout, None)
            taken.add(shipped["slug"])
            layout_views[view_layout] = shipped
            views.append(shipped)
        elif (seed := own.get(slug)) is not None:
            views.append(view(slug, seed.name, view_layout, seed.filters, seed))
    views.extend(
        view(preset.slug, preset.name, layout, preset.filters, preset)
        for preset in custom
    )
    if not any(each["is_default"] for each in views):
        layout_views[layout]["is_default"] = True
    return views


def _presets_to_views() -> None:
    bind = op.get_bind()
    presets: dict[int, list[Any]] = {}
    for preset in bind.execute(
        sa.text(
            "SELECT project_id, slug, name, is_default, filters, created_by,"
            " created_at, updated_at FROM project_filter_presets"
            " ORDER BY project_id, position, id"
        )
    ):
        presets.setdefault(preset.project_id, []).append(preset)

    rows: list[dict[str, Any]] = []
    for project in bind.execute(
        sa.text("SELECT id, initiative_id, default_view_mode FROM projects")
    ):
        own = presets.get(project.id, [])
        if _untouched(project, own):
            continue
        rows.extend(
            {
                **view,
                "definition": json.dumps(view["definition"]),
                "initiative_id": project.initiative_id,
                "tool_id": project.id,
                "position": position,
            }
            for position, view in enumerate(_project_views(project, own))
        )
    if not rows:
        return

    bind.execute(
        sa.text(
            "INSERT INTO tool_views (created_by, initiative_id, tool, tool_id,"
            " kind, name, slug, position, is_default, definition, created_at,"
            " updated_at)"
            " VALUES (:created_by, :initiative_id, 'project', :tool_id, 'view',"
            " :name, :slug, :position, :is_default, CAST(:definition AS jsonb),"
            " COALESCE(:created_at, now()), COALESCE(:updated_at, now()))"
        ),
        rows,
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.create_table(
        "project_filter_presets",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "slug", name="uq_project_filter_presets_slug"
        ),
    )
    op.create_index(
        "ix_project_filter_presets_one_default",
        "project_filter_presets",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        "ix_project_filter_presets_project_id",
        "project_filter_presets",
        ["project_id"],
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER tr_project_filter_presets_set_created_by "
        "BEFORE INSERT ON project_filter_presets "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )

    _lifted(("tool_views", "projects"), _views_to_presets)

    op.drop_table("tool_views")


def _views_to_presets() -> None:
    bind = op.get_bind()
    views = bind.execute(
        sa.text(
            "SELECT tool_id, slug, name, is_default, definition, created_by,"
            " created_at, updated_at FROM tool_views"
            " WHERE tool = 'project' AND kind = 'view'"
            " ORDER BY tool_id, position, id"
        )
    ).all()
    presets: list[dict[str, Any]] = []
    positions: dict[int, int] = {}
    for view in views:
        definition = view.definition
        if "filters" not in definition or set(definition) - {"layout", "filters"}:
            continue
        position = positions.get(view.tool_id, 0)
        positions[view.tool_id] = position + 1
        presets.append(
            {
                "project_id": view.tool_id,
                "slug": view.slug,
                "name": view.name,
                "position": position,
                "is_default": view.is_default,
                "filters": json.dumps(definition["filters"]),
                "created_by": view.created_by,
                "created_at": view.created_at,
                "updated_at": view.updated_at,
            }
        )
    stored = {view.tool_id for view in views}
    for project_id in bind.execute(sa.text("SELECT id FROM projects")).scalars():
        if project_id in stored:
            continue
        presets.extend(
            {
                "project_id": project_id,
                "slug": slug,
                "name": name,
                "position": position,
                "is_default": slug == "all",
                "filters": json.dumps(filters),
                "created_by": None,
                "created_at": None,
                "updated_at": None,
            }
            for position, (slug, (name, filters)) in enumerate(_SEEDS.items())
        )
    if presets:
        bind.execute(
            sa.text(
                "INSERT INTO project_filter_presets (created_by, project_id, slug,"
                " name, position, is_default, filters, created_at, updated_at)"
                " VALUES (:created_by, :project_id, :slug, :name, :position,"
                " :is_default, CAST(:filters AS jsonb),"
                " COALESCE(:created_at, now()), COALESCE(:updated_at, now()))"
            ),
            presets,
        )
