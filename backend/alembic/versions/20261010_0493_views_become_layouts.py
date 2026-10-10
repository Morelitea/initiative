"""views become layouts

``tool_views`` becomes ``tool_layouts``, in every guild schema: one row per
kind of layout a target has changed, rather than a target's whole set. A
target is one instance of a tool (a project) or, for a tool the initiative
shares, the initiative (``tool_id`` NULL). A row's ``kind`` is one way the
target lists its items (``table``, ``board``, ``calendar``), how it shows one
of them (``task``), or which list it opens on (``default``, ``{"kind": …}``).
A layout is stored when it is changed, so its ``updated_at`` is its own; what
is not stored is drawn as shipped. Its policies, change capture and freeze are
rendered by the provisioning run.

A list layout holds how what it lists is drawn (a board's card, a table's
columns); what a person narrows a list to, and how they sort it, are theirs. So from each target's stored views:

* each list kind keeps what the view of that kind drew, read from the view
  with that kind's slug, or else the first of that kind holding no filters,
  and is stored only if that says anything;
* the default is kept where it is not the shipped one (a project's table);
* an item layout keeps its definition, under its item kind;
* the views that only filtered a list are not kept.

The downgrade gives every project holding a layout the six views a project
shipped, each list view with what its layout drew and the default it opened
on, and its task layout back. A shared tool's list layouts, which views could
not hold, are not kept.

Revision ID: 20261010_0493
Revises: 20261010_0492
Create Date: 2026-10-10
"""

import json
from typing import Any, Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0493"
down_revision = "20261010_0492"
branch_labels = None
depends_on = None

#: The ways a target listed its items at this revision, in order, the first
#: the shipped default, by tool.
_LISTS: dict[str, tuple[str, ...]] = {
    "project": ("table", "board", "calendar"),
    "calendar": ("calendar",),
}
#: What a list layout holds.
_LIST_KEYS = ("card", "columns")
_DEFAULT = "default"
#: The views a project shipped before this revision: (slug, name, layout,
#: filters).
_SHIPPED: tuple[tuple[str, str, str, Optional[dict[str, Any]]], ...] = (
    ("table", "Table", "table", None),
    ("board", "Board", "board", None),
    ("calendar", "Calendar", "calendar", None),
    (
        "incomplete",
        "Incomplete",
        "table",
        {"status_categories": ["backlog", "todo", "in_progress"]},
    ),
    ("unassigned", "Unassigned", "table", {"assignees": ["none"]}),
    ("mine", "Mine", "table", {"assignees": ["me"]}),
)
_TARGET = ["initiative_id", "tool", "tool_id"]
_TOOL_CHECK = (
    "tool IN ('project', 'queue', 'counter_group', 'gallery', 'calendar', 'post')"
)
_TARGET_CHECK = "(tool IN ('calendar', 'post')) = (tool_id IS NULL)"


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


def _created_by_trigger(table: str) -> None:
    op.execute(
        f"CREATE OR REPLACE TRIGGER tr_{table}_set_created_by "
        f"BEFORE INSERT ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "tool_layouts",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=32), nullable=False),
        sa.Column("tool_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_TOOL_CHECK, name="ck_tool_layouts_tool"),
        sa.CheckConstraint(_TARGET_CHECK, name="ck_tool_layouts_target"),
        sa.CheckConstraint(
            "kind IN ('table', 'board', 'calendar', 'task', 'calendar_event',"
            " 'default')",
            name="ck_tool_layouts_kind",
        ),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_layouts_initiative_id", "tool_layouts", ["initiative_id"])
    op.create_index(
        "uq_tool_layouts_kind",
        "tool_layouts",
        [*_TARGET, "kind"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    _created_by_trigger("tool_layouts")

    # Filled before the provisioning run gives it row security; the views it
    # is filled from are read with theirs lifted.
    _lifted(("tool_views",), _views_to_layouts)

    op.drop_table("tool_views")


def _layout_of(view: Any) -> Optional[str]:
    layout = view.definition.get("layout")
    return layout.get("type") if isinstance(layout, dict) else None


def _views_to_layouts() -> None:
    bind = op.get_bind()
    targets: dict[tuple[Any, ...], list[Any]] = {}
    for row in bind.execute(
        sa.text(
            "SELECT initiative_id, tool, tool_id, kind, item_kind, slug,"
            " is_default, definition, created_by, created_at, updated_at"
            " FROM tool_views ORDER BY position, id"
        )
    ):
        targets.setdefault((row.initiative_id, row.tool, row.tool_id), []).append(row)

    layouts: list[dict[str, Any]] = []
    for (initiative_id, tool, tool_id), rows in targets.items():

        def layout(kind: str, definition: dict[str, Any], source: Any) -> None:
            layouts.append(
                {
                    "initiative_id": initiative_id,
                    "tool": tool,
                    "tool_id": tool_id,
                    "kind": kind,
                    "definition": json.dumps(definition),
                    "created_by": source.created_by,
                    "created_at": source.created_at,
                    "updated_at": source.updated_at,
                }
            )

        views = [row for row in rows if row.kind == "view"]
        lists = _LISTS.get(tool, ())
        for kind in lists:
            drawn = [
                view
                for view in views
                if _layout_of(view) == kind and "filters" not in view.definition
            ]
            view = next((view for view in drawn if view.slug == kind), None) or next(
                iter(drawn), None
            )
            if view is None:
                continue
            definition = {
                key: view.definition[key]
                for key in _LIST_KEYS
                if key in view.definition
            }
            if definition:
                layout(kind, definition, view)
        opened = next((view for view in views if view.is_default), None)
        if opened is not None and lists:
            kind = _layout_of(opened)
            if kind in lists and kind != lists[0]:
                layout(_DEFAULT, {"kind": kind}, opened)
        for row in rows:
            if row.kind == "item_layout":
                layout(row.item_kind, dict(row.definition), row)

    if layouts:
        bind.execute(
            sa.text(
                "INSERT INTO tool_layouts (created_by, initiative_id, tool,"
                " tool_id, kind, definition, created_at, updated_at)"
                " VALUES (:created_by, :initiative_id, :tool, :tool_id, :kind,"
                " CAST(:definition AS jsonb), :created_at, :updated_at)"
            ),
            layouts,
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
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
        sa.CheckConstraint(_TOOL_CHECK, name="ck_tool_views_tool"),
        sa.CheckConstraint(_TARGET_CHECK, name="ck_tool_views_target"),
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
    _created_by_trigger("tool_views")

    _lifted(("tool_layouts",), _layouts_to_views)

    op.drop_table("tool_layouts")


def _layouts_to_views() -> None:
    bind = op.get_bind()
    targets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in bind.execute(
        sa.text(
            "SELECT initiative_id, tool, tool_id, kind, definition, created_by,"
            " created_at, updated_at FROM tool_layouts ORDER BY id"
        )
    ):
        targets.setdefault((row.initiative_id, row.tool, row.tool_id), {})[row.kind] = (
            row
        )

    rows: list[dict[str, Any]] = []
    for (initiative_id, tool, tool_id), stored in targets.items():
        base = {
            "initiative_id": initiative_id,
            "tool": tool,
            "tool_id": tool_id,
            "item_kind": None,
            "name": None,
            "slug": None,
            "position": 0,
            "is_default": False,
            "created_by": None,
            "created_at": None,
            "updated_at": None,
        }
        if tool == "project":
            opened = stored.get(_DEFAULT)
            default = opened.definition.get("kind") if opened is not None else None
            if default not in _LISTS["project"]:
                default = "table"
            for position, (slug, name, kind, filters) in enumerate(_SHIPPED):
                definition: dict[str, Any] = {"layout": {"type": kind}}
                if filters is not None:
                    definition["filters"] = filters
                drawn = stored.get(slug)
                if drawn is not None:
                    definition.update(drawn.definition)
                rows.append(
                    {
                        **base,
                        "kind": "view",
                        "name": name,
                        "slug": slug,
                        "position": position,
                        "is_default": slug == default,
                        "definition": json.dumps(definition),
                        **(
                            {
                                "created_by": drawn.created_by,
                                "created_at": drawn.created_at,
                                "updated_at": drawn.updated_at,
                            }
                            if drawn is not None
                            else {}
                        ),
                    }
                )
        if "task" in stored:
            task = stored["task"]
            rows.append(
                {
                    **base,
                    "kind": "item_layout",
                    "item_kind": "task",
                    "definition": json.dumps(task.definition),
                    "created_by": task.created_by,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
            )

    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO tool_views (created_by, initiative_id, tool, tool_id,"
                " kind, item_kind, name, slug, position, is_default, definition,"
                " created_at, updated_at)"
                " VALUES (:created_by, :initiative_id, :tool, :tool_id, :kind,"
                " :item_kind, :name, :slug, :position, :is_default,"
                " CAST(:definition AS jsonb), COALESCE(:created_at, now()),"
                " COALESCE(:updated_at, now()))"
            ),
            rows,
        )
