"""Tests for Discretionary Access Control (DAC) — project and document permissions.

Tests cover:
- Generic helpers (effective_permission_level)
- Project permission computation and enforcement
- Document permission computation and enforcement

Uses SimpleNamespace mocks to simulate eagerly-loaded ORM objects.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.messages import DocumentMessages, ProjectMessages
from app.models.document import DocumentPermissionLevel
from app.models.project import ProjectPermissionLevel
from app.models.user import UserRole
from app.services.permissions import (
    PROJECT_LEVEL_ORDER,
    compute_document_permission,
    compute_project_permission,
    effective_permission_level,
    has_project_write_access,
    require_document_access,
    require_project_access,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, role: UserRole = UserRole.member) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role)


def _make_project(
    *,
    user_id: int | None = None,
    user_level: ProjectPermissionLevel | None = None,
    role_permissions: list | None = None,
    memberships: list | None = None,
    guild_id: int = 1,
) -> SimpleNamespace:
    """Build a mock project with eagerly-loaded relationships."""
    permissions = []
    if user_id is not None and user_level is not None:
        permissions.append(SimpleNamespace(user_id=user_id, level=user_level))
    return SimpleNamespace(
        guild_id=guild_id,
        permissions=permissions,
        role_permissions=role_permissions or [],
        initiative=SimpleNamespace(memberships=memberships or []),
    )


def _make_document(
    *,
    user_id: int | None = None,
    user_level: DocumentPermissionLevel | None = None,
    role_permissions: list | None = None,
    memberships: list | None = None,
    guild_id: int = 1,
) -> SimpleNamespace:
    """Build a mock document with eagerly-loaded relationships."""
    permissions = []
    if user_id is not None and user_level is not None:
        permissions.append(SimpleNamespace(user_id=user_id, level=user_level))
    return SimpleNamespace(
        guild_id=guild_id,
        permissions=permissions,
        role_permissions=role_permissions or [],
        initiative=SimpleNamespace(memberships=memberships or []),
    )


# ---------------------------------------------------------------------------
# effective_permission_level (generic helper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_effective_permission_level_both_none():
    result = effective_permission_level(None, None, PROJECT_LEVEL_ORDER)
    assert result is None


@pytest.mark.unit
def test_effective_permission_level_user_only():
    result = effective_permission_level(
        ProjectPermissionLevel.read,
        None,
        PROJECT_LEVEL_ORDER,
    )
    assert result == ProjectPermissionLevel.read


@pytest.mark.unit
def test_effective_permission_level_role_only():
    result = effective_permission_level(
        None,
        ProjectPermissionLevel.write,
        PROJECT_LEVEL_ORDER,
    )
    assert result == ProjectPermissionLevel.write


@pytest.mark.unit
def test_effective_permission_level_takes_higher():
    result = effective_permission_level(
        ProjectPermissionLevel.read,
        ProjectPermissionLevel.owner,
        PROJECT_LEVEL_ORDER,
    )
    assert result == ProjectPermissionLevel.owner

    # Also verify the reverse: user > role
    result2 = effective_permission_level(
        ProjectPermissionLevel.owner,
        ProjectPermissionLevel.read,
        PROJECT_LEVEL_ORDER,
    )
    assert result2 == ProjectPermissionLevel.owner


# ---------------------------------------------------------------------------
# compute_project_permission
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_project_permission_guild_admin_no_dac():
    """Guild admin with no DAC grant gets no access (no admin bypass)."""
    project = _make_project()
    result = compute_project_permission(project, user_id=1)
    assert result is None


@pytest.mark.unit
def test_compute_project_permission_user_read():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    result = compute_project_permission(project, user_id=1)
    assert result == "read"


@pytest.mark.unit
def test_compute_project_permission_no_access():
    project = _make_project()
    result = compute_project_permission(project, user_id=1)
    assert result is None


@pytest.mark.unit
def test_compute_project_permission_role_elevates():
    """Role-based permission higher than user permission should take effect."""
    role_id = 10
    project = _make_project(
        user_id=1,
        user_level=ProjectPermissionLevel.read,
        role_permissions=[
            SimpleNamespace(
                initiative_role_id=role_id, level=ProjectPermissionLevel.write
            ),
        ],
        memberships=[
            SimpleNamespace(user_id=1, role_id=role_id),
        ],
    )
    result = compute_project_permission(project, user_id=1)
    assert result == "write"


# ---------------------------------------------------------------------------
# require_project_access
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_require_project_access_read_allowed():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    user = _make_user(user_id=1)
    require_project_access(project, user, access="read")  # should not raise


@pytest.mark.unit
def test_require_project_access_write_denied_for_reader():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, access="write")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ProjectMessages.WRITE_ACCESS_REQUIRED


@pytest.mark.unit
def test_require_project_access_no_access():
    project = _make_project()  # no permissions for user_id=1
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, access="read")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ProjectMessages.NO_ACCESS


@pytest.mark.unit
def test_require_project_access_owner_required():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.write)
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, require_owner=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ProjectMessages.OWNER_REQUIRED


@pytest.mark.unit
def test_require_project_access_owner_passes():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.owner)
    user = _make_user(user_id=1)
    require_project_access(project, user, require_owner=True)  # should not raise


# ---------------------------------------------------------------------------
# has_project_write_access
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_has_project_write_access_true_for_write():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.write)
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is True


@pytest.mark.unit
def test_has_project_write_access_true_for_owner():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.owner)
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is True


@pytest.mark.unit
def test_has_project_write_access_false_for_read():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is False


@pytest.mark.unit
def test_has_project_write_access_false_for_none():
    project = _make_project()  # no permissions
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is False


# ---------------------------------------------------------------------------
# compute_document_permission
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_document_permission_guild_admin_no_dac():
    """Guild admin with no DAC grant gets no access (no admin bypass)."""
    doc = _make_document()
    result = compute_document_permission(doc, user_id=1)
    assert result is None


@pytest.mark.unit
def test_compute_document_permission_user_write():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.write)
    result = compute_document_permission(doc, user_id=1)
    assert result == "write"


@pytest.mark.unit
def test_compute_document_permission_no_access():
    doc = _make_document()
    result = compute_document_permission(doc, user_id=1)
    assert result is None


# ---------------------------------------------------------------------------
# require_document_access (patches _get_loaded_document_permissions to avoid
# SQLAlchemy inspect on SimpleNamespace)
# ---------------------------------------------------------------------------


_PATCH_TARGET = "app.services.permissions._get_loaded_document_permissions"


@pytest.mark.unit
def test_require_document_access_read_allowed():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.read)
    user = _make_user(user_id=1)
    with patch(_PATCH_TARGET, return_value=doc.permissions):
        require_document_access(doc, user, access="read")  # should not raise


@pytest.mark.unit
def test_require_document_access_write_denied():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.read)
    user = _make_user(user_id=1)
    with patch(_PATCH_TARGET, return_value=doc.permissions):
        with pytest.raises(HTTPException) as exc_info:
            require_document_access(doc, user, access="write")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == DocumentMessages.WRITE_ACCESS_REQUIRED


@pytest.mark.unit
def test_require_document_access_no_access():
    doc = _make_document()  # no permissions for user
    user = _make_user(user_id=1)
    with patch(_PATCH_TARGET, return_value=doc.permissions):
        with pytest.raises(HTTPException) as exc_info:
            require_document_access(doc, user, access="read")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == DocumentMessages.NO_ACCESS


@pytest.mark.unit
def test_require_document_access_owner_required():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.write)
    user = _make_user(user_id=1)
    with patch(_PATCH_TARGET, return_value=doc.permissions):
        with pytest.raises(HTTPException) as exc_info:
            require_document_access(doc, user, require_owner=True)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == DocumentMessages.OWNER_REQUIRED


@pytest.mark.unit
def test_require_document_access_owner_passes():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.owner)
    user = _make_user(user_id=1)
    with patch(_PATCH_TARGET, return_value=doc.permissions):
        require_document_access(doc, user, require_owner=True)  # should not raise


# ---------------------------------------------------------------------------
# my_permission_level reflects an active PAM grant (drives edit affordances)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_project_permission_lifts_to_grant():
    """A grantee has no permission row; ``my_permission_level`` must reflect the
    grant so the UI shows edit affordances for a read_write grant."""
    from app.core.pam_context import set_active_grant

    project = _make_project()  # no DAC permission rows
    project.guild_id = 7
    try:
        set_active_grant(None, None)
        assert compute_project_permission(project, 99) is None

        set_active_grant(7, "read")
        assert compute_project_permission(project, 99) == "read"

        set_active_grant(7, "read_write")
        assert compute_project_permission(project, 99) == "write"

        # A grant never confers owner, and never bleeds across guilds.
        set_active_grant(8, "read_write")
        assert compute_project_permission(project, 99) is None
    finally:
        set_active_grant(None, None)


@pytest.mark.unit
def test_compute_document_permission_lifts_to_grant():
    from app.core.pam_context import set_active_grant

    doc = _make_document()
    doc.guild_id = 7
    try:
        set_active_grant(7, "read_write")
        assert compute_document_permission(doc, 99) == "write"
        set_active_grant(7, "read")
        assert compute_document_permission(doc, 99) == "read"
    finally:
        set_active_grant(None, None)


@pytest.mark.unit
def test_compute_project_permission_grant_does_not_downgrade_dac():
    """An explicit owner permission outranks the grant (no downgrade to write)."""
    from app.core.pam_context import set_active_grant

    project = _make_project(user_id=99, user_level=ProjectPermissionLevel.owner)
    project.guild_id = 7
    try:
        set_active_grant(7, "read_write")
        assert compute_project_permission(project, 99) == "owner"
    finally:
        set_active_grant(None, None)
