"""Coverage tests — every tool is wired into every per-tool surface.

The tools are uniform, so instead of a mirror registry these assert directly that
each real surface (the DAC registries, the soft-delete model list, the purge
worker, the trash listing) covers the whole ``Tool`` enum / every soft-deletable
model. A new tool — or a new soft-delete model — that forgets one of them fails
here. This is the "confirm all tools have similar surface coverage" guarantee,
kept honest against the actual sources rather than a re-declared list.
"""

from app.core.tools import Tool


def test_resource_grant_schema_takes_the_tool_enum():
    # resource_grants rows and schemas are typed by the Tool enum itself — no
    # parallel string list anywhere.
    from app.models.tenant.resource_grant import ResourceGrant
    from app.schemas.tenant.resource_grant import ResourceGrantBulkItem

    assert ResourceGrant.model_fields["resource_type"].annotation is Tool
    assert ResourceGrantBulkItem.model_fields["resource_type"].annotation is Tool


def test_dac_registries_cover_every_tool():
    from app.api.resource_access import GRANTABLE_KINDS, RESOURCE_ACCESS
    from app.services.permissions import DAC_RESOURCES

    # Every tool is a local DAC resource; the three registries must agree and span
    # the whole enum. A new tool that forgets one of them fails here.
    assert set(DAC_RESOURCES) == set(Tool)
    assert set(RESOURCE_ACCESS) == set(Tool)
    assert set(GRANTABLE_KINDS) == set(Tool)


def test_purge_worker_covers_every_soft_delete_model():
    # The invariant that caught the missing CounterGroup/Counter drift: every
    # soft-deletable model must be reachable by the auto-purge worker, else an
    # independently-trashed row of that type never purges past retention.
    from app.db.soft_delete_filter import SOFT_DELETE_MODELS
    from app.services.tenant.trash_purge import _PURGE_TOP_DOWN

    assert set(_PURGE_TOP_DOWN) == set(SOFT_DELETE_MODELS)


def test_trash_listing_covers_every_soft_delete_model():
    # Every soft-deletable model must be listable in the trash can, else a trashed
    # row of that type is invisible (and unrestorable) to the user.
    from app.api.v1.tenant_endpoints.trash import ENTITY_REGISTRY
    from app.db.soft_delete_filter import SOFT_DELETE_MODELS

    listed = {model for model, _name_field in ENTITY_REGISTRY.values()}
    assert set(SOFT_DELETE_MODELS) <= listed


def test_permission_keys_are_exactly_the_derived_tool_pairs():
    # Every tool has a `{plural}_enabled` + `create_{plural}` PermissionKey pair
    # spelled exactly as the Tool enum derives it, and nothing else exists. A new
    # tool that forgets its keys — or a key that drifts from the canonical stem —
    # fails here.
    from app.models.tenant.initiative import (
        BUILTIN_ROLE_PERMISSIONS,
        DEFAULT_PERMISSION_VALUES,
        PermissionKey,
    )

    derived = {t.view_permission for t in Tool} | {t.create_permission for t in Tool}
    assert {k.value for k in PermissionKey} == derived
    assert set(DEFAULT_PERMISSION_VALUES) == set(PermissionKey)
    for role_permissions in BUILTIN_ROLE_PERMISSIONS.values():
        assert set(role_permissions) == set(PermissionKey)


def test_initiative_master_switches_are_exactly_the_toggleable_tools():
    # Every non-core tool has an initiative-level `{plural}_enabled` master
    # switch (model column + read/create/update schema fields); core tools are
    # always-on and must NOT grow one.
    from app.core.tools import CORE_TOOLS, TOGGLEABLE_TOOLS
    from app.models.tenant.initiative import Initiative
    from app.schemas.tenant.initiative import InitiativeBase, InitiativeUpdate

    switches = {t.view_permission for t in TOGGLEABLE_TOOLS}
    model_fields = set(Initiative.model_fields)
    schema_fields = set(InitiativeBase.model_fields)
    update_fields = set(InitiativeUpdate.model_fields)
    assert switches <= model_fields
    assert switches <= schema_fields
    assert switches <= update_fields
    for core in CORE_TOOLS:
        assert core.view_permission not in model_fields
        assert core.view_permission not in schema_fields


def test_member_read_flags_are_exactly_the_derived_tool_pairs():
    # InitiativeMemberRead carries one can_view/can_create pair per tool, spelled
    # exactly as the Tool enum derives them.
    from app.schemas.tenant.initiative import InitiativeMemberRead

    fields = set(InitiativeMemberRead.model_fields)
    for t in Tool:
        assert t.member_view_field in fields
        assert t.member_create_field in fields
    flag_fields = {f for f in fields if f.startswith(("can_view_", "can_create_"))}
    derived = {t.member_view_field for t in Tool} | {
        t.member_create_field for t in Tool
    }
    assert flag_fields == derived


def test_recent_entity_types_agree_across_surfaces():
    # The model's allowed set, the schema enum, and the RLS path registry all
    # derive from RECENTABLE_TOOLS — assert they agree and stay within the Tool
    # enum (this also guards someone re-declaring one of them by hand).
    from app.core.tools import RECENTABLE_TOOLS
    from app.db.initiative_rls import RECENT_ENTITY_TABLES
    from app.models.tenant.recent_view import RECENT_ENTITY_TYPES
    from app.schemas.tenant.recent_view import RecentEntityType

    derived = {t.value for t in RECENTABLE_TOOLS}
    assert set(RECENT_ENTITY_TYPES) == derived
    assert set(RECENT_ENTITY_TABLES) == derived
    assert {e.value for e in RecentEntityType} == derived
    assert derived <= {t.value for t in Tool}


def test_export_adapters_cover_exactly_the_bulk_export_tools():
    """The export-engine adapter registry and the tool registry must agree:
    every BULK_EXPORT_TOOLS member has an adapter keyed by its kebab-singular
    source name, and the only non-tool source is the tasks sub-resource. A
    new exportable tool (or a renamed source) fails here instead of shipping
    a bulk-export flag with no engine behind it."""
    from app.core.tools import BULK_EXPORT_TOOLS, Tool, tool_export_source
    from app.services.export.adapters import ADAPTERS

    derived = {tool_export_source(tool) for tool in BULK_EXPORT_TOOLS}
    extra = set(ADAPTERS) - derived
    assert derived <= set(ADAPTERS), f"missing adapters for {derived - set(ADAPTERS)}"
    # "tasks" is a project sub-resource (the filterable task list), not a Tool.
    assert extra == {"tasks"}, f"unregistered export sources: {extra - {'tasks'}}"
    # Tools without the flag must not silently grow an adapter either.
    unflagged = {
        tool_export_source(t) for t in Tool if t not in BULK_EXPORT_TOOLS
    } & set(ADAPTERS)
    assert not unflagged, (
        f"adapter exists but tool not in BULK_EXPORT_TOOLS: {unflagged}"
    )
