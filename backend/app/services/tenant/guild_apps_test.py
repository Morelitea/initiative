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

from app.models.tenant.guild_app import GuildApp
from app.services.marketplace.definitions import MOUNTABLE_TOOLS
from app.services.tenant.guild_apps import (
    ARTIFACT_HANDLERS,
    PlacementError,
    app_artifacts,
    get_app_content_id,
    legacy_artifacts,
    normalize_placement,
    placed_in,
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


class TestPlacement:
    """Where an app's initiative surfaces appear.

    Three states with one representation each, so a reader never has to work out
    which of two shapes meant the same thing.
    """

    def test_saying_nothing_means_every_initiative(self):
        assert normalize_placement(None, initiative_ids={1, 2}) == {}
        assert normalize_placement({}, initiative_ids={1, 2}) == {}

    def test_an_admin_may_narrow_it(self):
        assert normalize_placement({"initiatives": [2, 1]}, initiative_ids={1, 2}) == {
            "initiatives": [1, 2]
        }

    def test_naming_none_is_a_choice_rather_than_an_accident(self):
        # Keeps the guild-wide surface and drops the per-initiative ones, which
        # is a different wish from turning the whole app off.
        assert normalize_placement({"initiatives": []}, initiative_ids={1}) == {
            "initiatives": []
        }

    def test_a_repeated_id_is_stored_once(self):
        assert normalize_placement({"initiatives": [1, 1]}, initiative_ids={1}) == {
            "initiatives": [1]
        }

    def test_it_may_only_name_this_guild_s_initiatives(self):
        with pytest.raises(PlacementError, match="not one of this guild"):
            normalize_placement({"initiatives": [9]}, initiative_ids={1, 2})

    def test_an_unknown_key_is_refused(self):
        with pytest.raises(PlacementError, match="does not take"):
            normalize_placement({"projects": [1]}, initiative_ids={1})

    @pytest.mark.parametrize("value", ["1", 1.5, True, None, {"id": 1}])
    def test_an_id_is_a_whole_number(self, value):
        with pytest.raises(PlacementError, match="list of ids"):
            normalize_placement({"initiatives": [value]}, initiative_ids={1})

    def test_it_must_be_an_object(self):
        with pytest.raises(PlacementError, match="must be an object"):
            normalize_placement([1, 2], initiative_ids={1})

    @staticmethod
    def _app(placement: dict) -> GuildApp:
        """An install carrying nothing but the placement under test."""
        return GuildApp(
            guild_id=1,
            listing_uid="0000000000000",
            listing_version="1.0.0",
            app_kind="service",
            name="WidgetCo",
            installed_by_id=1,
            placement=placement,
        )

    def test_an_unplaced_app_is_offered_everywhere(self):
        app = self._app({})
        assert placed_in(app, 1) is True
        assert placed_in(app, 99) is True

    def test_a_placed_app_is_offered_where_it_was_placed(self):
        app = self._app({"initiatives": [1]})
        assert placed_in(app, 1) is True
        assert placed_in(app, 2) is False

    def test_placement_says_nothing_about_the_guild_wide_reading(self):
        # There is one guild-wide surface, and narrowing where the initiative
        # ones appear does not move it.
        assert placed_in(self._app({"initiatives": []}), None) is True
