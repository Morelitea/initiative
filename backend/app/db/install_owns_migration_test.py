"""The owner-row trigger's body, as the migration that sets it states it.

``public.fn_install_owns_what_it_creates`` lives in ``public`` and is set by
migrations alone, so its source of truth is
``app.db.app_rls.INSTALL_OWNS_WHAT_IT_CREATES``. Revision 20260924_0385
restates it in full and keeps the body it replaces for its downgrade; these
hold both to what they name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.db.app_rls import INSTALL_OWNS_WHAT_IT_CREATES

pytestmark = pytest.mark.unit

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _migration(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_states_the_module_body():
    member_consents = _migration("20260924_0385_a_member_consents_per_purpose.py")
    assert member_consents.OWNS_FUNCTION_AFTER == INSTALL_OWNS_WHAT_IT_CREATES


def test_the_downgrade_restores_the_body_it_replaced():
    member_consents = _migration("20260924_0385_a_member_consents_per_purpose.py")
    scopes = _migration("20260924_0381_an_install_answers_to_its_scopes.py")
    assert member_consents.OWNS_FUNCTION_BEFORE == scopes.OWNS_FUNCTION
