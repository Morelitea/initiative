"""The session-standard migration reads both FORCE-RLS tables."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260917_0300_the_session_standard_is_the_communitys.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MIGRATION.stem, MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Scalar:
    def scalar_one(self) -> int:
        return 0


class _Connection:
    def execute(self, _statement) -> _Scalar:
        return _Scalar()


@pytest.mark.parametrize("into", ["guilds", "guild_administration"])
def test_carry_temporarily_lifts_rls_from_both_tables(monkeypatch, into: str) -> None:
    """The source and destination are visible for each carry direction."""
    migration = _migration()
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._carry(_Connection(), into=into)

    assert statements == [
        "ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY",
        "ALTER TABLE public.guild_administration NO FORCE ROW LEVEL SECURITY",
        "ALTER TABLE public.guild_administration FORCE ROW LEVEL SECURITY",
        "ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY",
    ]
