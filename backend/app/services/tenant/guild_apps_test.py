"""What an install produced, and how it is unmade.

Two properties, and both are about a list where there used to be a field.

The first is that **every mountable tool can be unmade**. Removal walks
``artifacts`` through a per-type handler, so a tool added to the manifest
vocabulary without one would install fine and quietly leave its row behind on
uninstall. The drift test refuses that combination at CI rather than at the
first uninstall.

The second is the **migration path**. Installs made before ``artifacts`` existed
recorded what they created under a per-tool key on ``config``. Migration
20260812_0171 rewrites them; ``legacy_artifacts`` is the same reading in Python,
so the rewrite's behaviour is pinned here without a database, and a row that
somehow escaped the migration still resolves rather than reading as an install
that created nothing.
"""

import pytest

from app.services.marketplace.definitions import MOUNTABLE_TOOLS
from app.services.tenant.guild_apps import (
    ARTIFACT_HANDLERS,
    app_artifacts,
    get_app_content_id,
    legacy_artifacts,
    requires_guild_admin,
)

pytestmark = pytest.mark.unit


class _App:
    """The two fields the artifact reading looks at."""

    def __init__(self, definition: dict, config: dict, artifacts: list | None = None):
        self.definition = definition
        self.config = config
        self.artifacts = artifacts if artifacts is not None else []


CALENDAR_APP = {"app_kind": "tool_instance", "tool": "calendar"}


class TestHandlerCoverage:
    def test_every_mountable_tool_can_be_unmade(self):
        """A tool an app may mount must have a handler, or uninstalling it would
        leave the row it created behind with nothing pointing at it."""
        assert MOUNTABLE_TOOLS <= set(ARTIFACT_HANDLERS)

    def test_no_handler_without_a_mountable_tool(self):
        """The other direction: a handler for something no manifest can name is
        dead code that reads as support."""
        assert set(ARTIFACT_HANDLERS) <= MOUNTABLE_TOOLS


class TestLegacyMigration:
    def test_a_pre_artifacts_install_still_resolves(self):
        app = _App(CALENDAR_APP, {"calendar_id": 7})
        assert app_artifacts(app) == [{"type": "calendar", "id": 7}]
        assert get_app_content_id(app) == 7

    def test_the_reading_is_guarded_on_the_tool(self):
        """A ``calendar_id`` that belongs to some other app's configuration is
        not an artifact — the pinned definition decides, not the key's name."""
        assert legacy_artifacts({"app_kind": "embed"}, {"calendar_id": 7}) == []
        assert legacy_artifacts({"app_kind": "service"}, {"calendar_id": 7}) == []

    def test_a_non_numeric_id_is_not_an_artifact(self):
        assert legacy_artifacts(CALENDAR_APP, {"calendar_id": "7"}) == []
        # ``True`` is an int in Python and would otherwise pass as id 1.
        assert legacy_artifacts(CALENDAR_APP, {"calendar_id": True}) == []

    def test_an_install_that_created_nothing_has_no_artifacts(self):
        assert legacy_artifacts(CALENDAR_APP, {}) == []
        assert app_artifacts(_App({"app_kind": "embed"}, {})) == []
        assert get_app_content_id(_App({"app_kind": "embed"}, {})) is None

    def test_the_new_shape_wins_over_the_old_key(self):
        """A migrated row keeps its own answer even if a stale config key
        survived — one source of truth, and it is the list."""
        app = _App(CALENDAR_APP, {"calendar_id": 7}, [{"type": "calendar", "id": 9}])
        assert app_artifacts(app) == [{"type": "calendar", "id": 9}]


class TestArtifactReading:
    def test_several_artifacts_are_all_returned(self):
        app = _App(
            {"app_kind": "tool_instance", "tool": "calendar"},
            {},
            [{"type": "calendar", "id": 1}, {"type": "calendar", "id": 2}],
        )
        assert [a["id"] for a in app_artifacts(app)] == [1, 2]

    def test_an_unknown_type_is_dropped(self):
        """Nothing can link to or remove it, so reporting it would promise
        something no code here can keep."""
        app = _App(CALENDAR_APP, {}, [{"type": "spreadsheet", "id": 3}])
        assert app_artifacts(app) == []

    def test_malformed_entries_are_dropped(self):
        app = _App(
            CALENDAR_APP,
            {},
            [
                "calendar",
                {"type": "calendar"},
                {"id": 4},
                {"type": "calendar", "id": 5},
            ],
        )
        assert app_artifacts(app) == [{"type": "calendar", "id": 5}]


class TestAdminOnly:
    def test_the_advanced_tool_embed_is_admin_only(self):
        assert (
            requires_guild_admin({"app_kind": "embed", "embed_target": "advanced_tool"})
            is True
        )

    def test_a_mounted_tool_is_governed_by_its_grants(self):
        assert requires_guild_admin(CALENDAR_APP) is False

    def test_a_service_app_is_not_admin_only(self):
        assert requires_guild_admin({"app_kind": "service"}) is False
