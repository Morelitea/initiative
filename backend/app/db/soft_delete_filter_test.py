"""Guards for the soft-delete registry — keep the explicit list honest.

``SOFT_DELETE_MODELS`` is hand-maintained (deliberately, so the ORM filter is
deterministic and survives import-order shuffles) rather than discovered at
runtime via ``SoftDeleteMixin.__subclasses__()``. That trades one risk for
another: a new soft-deletable model added to a table but forgotten here would
*silently leak its soft-deleted rows into every normal query* (the active-row
``deleted_at IS NULL`` criterion is only injected for models in the list).

This test closes that gap: the explicit list must equal the actual set of
mixin subclasses. CI fails the moment the two diverge, so the list keeps its
determinism without the drift.
"""

from app.db import base  # noqa: F401 — import side effect registers every model
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, SOFT_DELETE_TABLES
from app.models.tenant._mixins import SoftDeleteMixin


def _table_subclasses() -> set[type]:
    return {
        cls
        for cls in SoftDeleteMixin.__subclasses__()
        if isinstance(getattr(cls, "__tablename__", None), str)
    }


def test_soft_delete_models_matches_mixin_subclasses():
    listed = set(SOFT_DELETE_MODELS)
    actual = _table_subclasses()
    missing = actual - listed  # has the mixin but not in the filter list → leaks
    extra = listed - actual  # in the filter list but no longer a mixin subclass
    assert not missing, (
        "these models inherit SoftDeleteMixin but are missing from "
        "SOFT_DELETE_MODELS — their soft-deleted rows would leak into normal "
        f"queries: {sorted(c.__name__ for c in missing)}"
    )
    assert not extra, (
        "these are in SOFT_DELETE_MODELS but no longer inherit SoftDeleteMixin "
        f"— remove them: {sorted(c.__name__ for c in extra)}"
    )


def test_soft_delete_tables_matches_models():
    """The derived table-name tuple (read by the guild-RLS generator) stays in
    lockstep with SOFT_DELETE_MODELS."""
    assert set(SOFT_DELETE_TABLES) == {m.__tablename__ for m in SOFT_DELETE_MODELS}
