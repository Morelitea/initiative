"""Coverage tests — every tool is wired into every per-tool surface.

The tools are uniform, so instead of a mirror registry these assert directly that
each real surface (the DAC registries, the soft-delete model list, the purge
worker, the trash listing) covers the whole ``Tool`` enum / every soft-deletable
model. A new tool — or a new soft-delete model — that forgets one of them fails
here. This is the "confirm all tools have similar surface coverage" guarantee,
kept honest against the actual sources rather than a re-declared list.
"""

from app.core.tools import TOOL_TYPES, Tool


def test_resource_types_are_exactly_the_tools():
    # Every tool is a shareable resource_type, and nothing else is.
    assert TOOL_TYPES == frozenset(t.value for t in Tool)


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
