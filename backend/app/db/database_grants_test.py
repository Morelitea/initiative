"""The database-level TEMPORARY grant is revoked where roles are created.

The app creates no temporary objects, so it does not need the TEMPORARY grant
PUBLIC carries by default on a new database. Only a database's owner can change
its ACL, so this is applied where ``app_provisioner`` itself is created — the
compose ``initdb`` config for fresh installs, and
``scripts/create-provisioner.sql`` for deployments that predate it — never by a
migration, which runs as the provisioning role and cannot change a database ACL.

Only ``docker-compose.example.yml`` is tracked; an operator's own
``docker-compose.yml`` is gitignored and free to diverge.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_EXAMPLE = _REPO_ROOT / "docker-compose.example.yml"
_PROVISIONER_SQL = _REPO_ROOT / "backend" / "scripts" / "create-provisioner.sql"

_REVOKE = "REVOKE TEMPORARY ON DATABASE"


def test_fresh_installs_revoke_it_at_database_init():
    assert _COMPOSE_EXAMPLE.exists(), f"not found: {_COMPOSE_EXAMPLE}"
    _, _, initdb = _COMPOSE_EXAMPLE.read_text().partition("initdb-provisioner:")
    assert _REVOKE in initdb, (
        "the compose initdb config no longer revokes TEMPORARY, so a fresh "
        "install would be provisioned with a grant the app does not use"
    )


def test_existing_installs_have_the_same_revoke():
    assert _REVOKE in _PROVISIONER_SQL.read_text()


def test_the_revoke_is_verified_rather_than_assumed():
    """A REVOKE issued by a non-owner reports success and changes nothing, so
    the script confirms the grant is gone instead of trusting the exit code."""
    body = _PROVISIONER_SQL.read_text()
    assert "aclexplode" in body
    assert "RAISE EXCEPTION" in body
