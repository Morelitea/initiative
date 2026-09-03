"""The database-level TEMPORARY grant is revoked by the bootstrap.

The app creates no temporary objects, so it does not need the TEMPORARY grant
PUBLIC carries by default on a new database. Only a database's owner can change
its ACL, so this belongs to ``app.db.bootstrap`` — which connects as the owner —
rather than to a migration, which runs as the provisioning role.

These assert against the module rather than a deployment file: the bootstrap is
the one place the statement lives now, and an operator's own compose file is
free to differ.
"""

from __future__ import annotations

import pytest

from app.db.bootstrap import bootstrap_sql

pytestmark = pytest.mark.unit

_REVOKE = "REVOKE TEMPORARY ON DATABASE"


def test_the_bootstrap_revokes_it():
    assert _REVOKE in bootstrap_sql()


def test_the_revoke_is_verified_rather_than_assumed():
    """A REVOKE issued by a non-owner reports success and changes nothing, so
    the bootstrap reads the ACL back instead of trusting the exit."""
    body = bootstrap_sql()
    assert "aclexplode" in body
    assert "RAISE EXCEPTION" in body


def test_the_verification_follows_the_revoke():
    body = bootstrap_sql()
    assert body.index(_REVOKE) < body.index("aclexplode")
