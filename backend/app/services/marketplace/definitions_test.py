"""What a listing may declare, and what it is refused for.

These are pure-function tests: no database, no session, nothing to seed. The
validator is the whole boundary between a manifest someone wrote and a document
this build stores and later hands to a guild, so most of what matters is
expressed as "this is refused, by name" and "what is stored is canonical".

Three properties get the most attention, because they are the ones an
implementation could quietly lose:

* a definition never carries an address — only paths, joined later to a base URL
  the deployment supplies;
* what a manifest *declares* and what it *ships* cannot disagree;
* content this build assigns no meaning to (widget modules, sample rows, the
  automation block) is bounded and stored verbatim, never interpreted.
"""

import pytest

from app.services.marketplace import service_apps
from app.services.marketplace.definitions import (
    APP_KINDS,
    GUILD_INSTALLABLE_APP_KINDS,
    LISTING_SOURCES,
    ListingDefinitionError,
    app_widget_type,
    normalize_publisher,
    normalize_listing_definition,
    reserved_prefix_problem,
)
from app.services.marketplace.manifest_values import IDENTIFIER_CHARS
from app.services.marketplace.service_apps import EMBED_CAPABILITIES

pytestmark = pytest.mark.unit


def _label(text: str = "A label") -> dict[str, str]:
    return {"en": text}


def _service(**overrides) -> dict:
    """A minimal service app: declares nothing, ships nothing, and is valid.

    An app with no local features is a legitimate install — an integration that
    exists to give an external system a foothold in a guild has nothing to
    render — so the smallest valid manifest is the right starting point.
    """
    definition = {
        "app_kind": "service",
        "service": {"public_id": "tests.widget-co", "protocol": 1},
        "features": [],
    }
    definition.update(overrides)
    return definition


def _normalize(**overrides) -> dict:
    return normalize_listing_definition("app", _service(**overrides))


class TestAttribution:
    """Every listing states who publishes it, in one required name."""

    def test_a_listing_without_a_publisher_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="publisher is required"):
            normalize_publisher(None)

    def test_a_blank_name_is_not_a_name(self):
        with pytest.raises(ListingDefinitionError, match="publisher"):
            normalize_publisher("   ")

    def test_a_name_may_not_span_lines(self):
        # It is rendered on one line beside the listing; a value carrying its
        # own line breaks is refused rather than displayed however it lands.
        with pytest.raises(ListingDefinitionError, match="single line"):
            normalize_publisher("Widget Co\nby someone else")

    def test_a_name_is_kept_as_written(self):
        assert normalize_publisher("  Widget Co  ") == "Widget Co"

    def test_an_overlong_name_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="publisher"):
            normalize_publisher("W" * 500)


class TestReservedNamespace:
    """``core.*`` names listings shipped in this repository."""

    def test_a_built_in_may_use_it(self):
        assert reserved_prefix_problem("core.project-health", source="builtin") is None

    @pytest.mark.parametrize("source", sorted(LISTING_SOURCES - {"builtin"}))
    def test_no_other_source_may_claim_it(self, source):
        problem = reserved_prefix_problem("core.impostor", source=source)
        assert problem is not None
        assert "reserved" in problem

    def test_other_namespaces_are_open_to_everyone(self):
        for source in sorted(LISTING_SOURCES):
            assert reserved_prefix_problem("widgetco.thing", source=source) is None

    def test_the_prefix_is_matched_at_the_boundary(self):
        # 'coreutils.x' is somebody else's publisher, not the reserved one.
        assert reserved_prefix_problem("coreutils.x", source="registry") is None


class TestAppKinds:
    def test_service_is_publishable(self):
        assert "service" in APP_KINDS

    def test_service_is_installable_into_a_guild(self):
        """A service app has somewhere to land now: the registration supplies
        the address and the powers, and the install is the pinned definition
        plus whatever the guild configures against it."""
        assert "service" in GUILD_INSTALLABLE_APP_KINDS

    def test_installable_kinds_are_declared_kinds(self):
        """The two sets answer different questions — what a listing may declare
        versus what this build can mount — so a kind added to the vocabulary
        ahead of its machinery is refused rather than half-mounted."""
        assert GUILD_INSTALLABLE_APP_KINDS <= APP_KINDS

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown app kind"):
            normalize_listing_definition("app", {"app_kind": "daemon"})


class TestServiceIdentity:
    def test_a_service_names_itself(self):
        with pytest.raises(ListingDefinitionError, match="service.public_id"):
            normalize_listing_definition(
                "app", {"app_kind": "service", "service": {}, "features": []}
            )

    def test_the_service_id_is_publisher_scoped(self):
        with pytest.raises(ListingDefinitionError, match="publisher"):
            _normalize(service={"public_id": "noslug"})

    def test_a_protocol_this_build_does_not_speak_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="protocol"):
            _normalize(service={"public_id": "tests.widget-co", "protocol": 99})

    def test_the_protocol_defaults_to_the_one_this_build_speaks(self):
        definition = normalize_listing_definition(
            "app",
            {
                "app_kind": "service",
                "service": {"public_id": "tests.widget-co"},
                "features": [],
            },
        )
        assert definition["service"]["protocol"] == 1


class TestFeaturesMatchBlocks:
    """A declaration and a manifest body cannot disagree, in either direction."""

    def test_declaring_a_feature_with_no_block_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="is declared but"):
            _normalize(features=["widgets"])

    def test_shipping_a_block_without_declaring_it_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="is not declared"):
            _normalize(
                endpoints=[
                    {"id": "app.tests.widget-co.thing-happened", "direction": "emit"}
                ],
            )

    def test_an_unknown_feature_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown feature"):
            _normalize(features=["telemetry"])

    def test_an_empty_block_is_not_a_block(self):
        """Empty means absent, the same way for every block.

        A block that is present but empty describes nothing. Storing it would be
        a second shape meaning "none" — and one the feature cross-check could
        read differently from the way it was stored, letting a manifest carry a
        block its own ``features`` never declared.
        """
        definition = _normalize(endpoints=[])
        assert "endpoints" not in definition

        with pytest.raises(ListingDefinitionError, match="is declared but"):
            _normalize(features=["endpoints"], endpoints=[])

    def test_an_app_may_offer_no_local_features(self):
        definition = _normalize()
        assert definition["features"] == []
        assert "widgets" not in definition

    def test_features_are_stored_in_a_stable_order(self):
        definition = _normalize(
            features=["endpoints", "embeds", "endpoints"],
            endpoints=[
                {"id": "app.tests.widget-co.thing-happened", "direction": "emit"}
            ],
            embeds=[{"id": "main", "path": "/embed", "name": _label()}],
        )
        assert definition["features"] == ["embeds", "endpoints"]

    @pytest.mark.parametrize("feature", sorted(service_apps.FEATURES))
    def test_every_feature_names_a_block(self, feature):
        # The cross-check is only as complete as this map, so a feature added
        # without one would silently stop being checked.
        assert feature in service_apps.FEATURE_BLOCKS


class TestConnections:
    def test_a_static_connection_needs_something_to_supply(self):
        with pytest.raises(ListingDefinitionError, match="at least one field"):
            _normalize(
                connections=[
                    {"id": "shop", "scope": "static", "label": _label(), "fields": []}
                ]
            )

    def test_an_unknown_scope_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown scope"):
            _normalize(
                connections=[{"id": "shop", "scope": "global", "label": _label()}]
            )

    def test_an_interactive_connection_declares_where_to_start(self):
        with pytest.raises(ListingDefinitionError, match="connect_path"):
            _normalize(
                connections=[
                    {"id": "account", "scope": "interactive", "label": _label()}
                ]
            )

    def test_a_guild_credential_may_come_from_a_vendor_flow(self):
        """An admin runs the vendor's install once, for the whole guild.

        The alternative this replaces is an admin retyping an organization's
        name into a text box and hoping it names the same organization somebody
        installed at the vendor. Nothing about that is per-member, so the scope
        stays ``static``; the ``connect_path`` is how the value arrives.
        """
        [connection] = _normalize(
            connections=[
                {
                    "id": "workspace",
                    "scope": "static",
                    "label": _label(),
                    "connect_path": "/install/github",
                    "fields": [
                        {
                            "key": "owner",
                            "type": "string",
                            "label": _label(),
                            "managed": True,
                        }
                    ],
                }
            ]
        )["connections"]
        assert connection["connect_path"] == "/install/github"
        assert connection["fields"][0]["managed"] is True

    def test_a_guild_flow_needs_somewhere_to_put_its_result(self):
        """Every field typed means the app can never write the answer back.

        A static connection is satisfied by the values it holds, and only a
        ``managed`` field is one the app may write. So a flow with none can run
        to completion and leave the install exactly as unconfigured as it was.
        """
        with pytest.raises(ListingDefinitionError, match="managed field"):
            _normalize(
                connections=[
                    {
                        "id": "shop",
                        "scope": "static",
                        "label": _label(),
                        "connect_path": "/connect",
                        "fields": [
                            {"key": "token", "type": "secret", "label": _label()}
                        ],
                    }
                ]
            )

    def test_a_connect_path_is_a_path_and_not_an_address(self):
        for value in (
            "https://widget.test/connect",
            "//widget.test/connect",
            "/connect/../../admin",
            "connect",
        ):
            with pytest.raises(ListingDefinitionError, match="connect_path"):
                _normalize(
                    connections=[
                        {
                            "id": "account",
                            "scope": "interactive",
                            "label": _label(),
                            "connect_path": value,
                        }
                    ]
                )

    def test_an_unknown_field_type_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown field type"):
            _normalize(
                connections=[
                    {
                        "id": "shop",
                        "scope": "static",
                        "label": _label(),
                        "fields": [
                            {"key": "token", "type": "certificate", "label": _label()}
                        ],
                    }
                ]
            )

    def test_a_select_field_offers_its_values(self):
        with pytest.raises(ListingDefinitionError, match="at least one option"):
            _normalize(
                connections=[
                    {
                        "id": "shop",
                        "scope": "static",
                        "label": _label(),
                        "fields": [
                            {"key": "region", "type": "select", "label": _label()}
                        ],
                    }
                ]
            )

    def test_two_connections_cannot_share_an_id(self):
        connection = {
            "id": "shop",
            "scope": "static",
            "label": _label(),
            "fields": [{"key": "token", "type": "secret", "label": _label()}],
        }
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(connections=[connection, dict(connection)])

    def test_a_connection_is_stored_canonically(self):
        definition = _normalize(
            connections=[
                {
                    "id": "shop",
                    "scope": "static",
                    "label": _label("Storefront"),
                    "access_hint": {"api": "Storefront API", "scopes": ["read_items"]},
                    "fields": [
                        {
                            "key": "token",
                            "type": "secret",
                            "required": True,
                            "managed": True,
                            "label": _label("Token"),
                        }
                    ],
                    "unexpected": "dropped",
                }
            ]
        )
        assert definition["connections"] == [
            {
                "id": "shop",
                "scope": "static",
                "label": {"en": "Storefront"},
                "fields": [
                    {
                        "key": "token",
                        "type": "secret",
                        "required": True,
                        "label": {"en": "Token"},
                        "managed": True,
                    }
                ],
                "access_hint": {"api": "Storefront API", "scopes": ["read_items"]},
            }
        ]


#: The id the fixtures below read, spelled once. Namespaced under the fixture
#: app's own service id, which is what every endpoint id has to be.
READ_ID = "app.tests.widget-co.orders"


def _with_source(**endpoint_overrides) -> dict:
    """A service app with one connection and one read endpoint that needs it."""
    endpoint = {
        "id": READ_ID,
        "direction": "read",
        "requires": {"all_of": ["shop"]},
    }
    endpoint.update(endpoint_overrides)
    return _normalize(
        features=["endpoints"],
        connections=[
            {
                "id": "shop",
                "scope": "static",
                "label": _label(),
                "fields": [{"key": "token", "type": "secret", "label": _label()}],
            }
        ],
        endpoints=[endpoint],
    )


class TestRequires:
    def test_an_item_may_only_require_a_connection_that_exists(self):
        with pytest.raises(ListingDefinitionError, match="unknown connection"):
            _with_source(requires={"all_of": ["nope"]})

    def test_one_operator_at_a_time(self):
        with pytest.raises(ListingDefinitionError, match="exactly one"):
            _with_source(requires={"all_of": ["shop"], "any_of": ["shop"]})

    def test_an_empty_expression_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="names no connection"):
            _with_source(requires={"any_of": []})

    def test_omitting_it_means_always_available(self):
        definition = _with_source(requires=None)
        assert "requires" not in definition["endpoints"][0]

    def test_a_repeated_term_is_stored_once(self):
        definition = _with_source(requires={"any_of": ["shop", "shop"]})
        assert definition["endpoints"][0]["requires"] == {"any_of": ["shop"]}


class TestEndpoints:
    def test_an_id_is_namespaced_under_the_app(self):
        # Two apps offering `create-issue` would be two different things under
        # one name, and a caller resolving the wrong one would do the wrong
        # thing successfully.
        for value in ("orders", "app.someone.else.orders", "app.tests.widget-co."):
            with pytest.raises(ListingDefinitionError, match="must start with"):
                _with_source(id=value)

    def test_a_direction_is_required_and_closed(self):
        # Direction decides who may call it, whether an answer may be cached,
        # and whether a widget may bind it — so an endpoint without one is not a
        # partial declaration, it is an unanswerable question.
        with pytest.raises(ListingDefinitionError, match="direction"):
            _with_source(direction=None)
        with pytest.raises(ListingDefinitionError, match="direction"):
            _with_source(direction="sideways")

    def test_an_unknown_visibility_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown visibility"):
            _with_source(visibility="everyone")

    def test_visibility_defaults_to_members_of_the_installing_guild(self):
        assert _with_source()["endpoints"][0]["visibility"] == "member"

    def test_a_cache_window_is_clamped_rather_than_refused(self):
        definition = _with_source(cache_ttl_seconds=10_000_000)
        ttl = definition["endpoints"][0]["cache_ttl_seconds"]
        assert ttl == service_apps.MAX_CACHE_TTL_SECONDS

    def test_only_a_read_is_cached_or_gated(self):
        # A write is authorized by the token that carried it and answers once,
        # so neither a rung nor a window means anything on one.
        for absent in ("cache_ttl_seconds", "visibility"):
            with pytest.raises(ListingDefinitionError, match="only a read"):
                _with_source(
                    direction="write", **{absent: 60 if "cache" in absent else "member"}
                )

    def test_an_emission_carries_nothing_a_caller_would_send(self):
        # Nobody calls it, so there is nothing to send, nothing to cache and
        # nobody to gate. Carrying any of it would describe a call that never
        # happens.
        with pytest.raises(ListingDefinitionError, match="has no requires"):
            _with_source(direction="emit")

    def test_an_actor_list_is_drawn_from_the_closed_set(self):
        with pytest.raises(ListingDefinitionError, match="actors"):
            _with_source(actors=["nobody"])
        with pytest.raises(ListingDefinitionError, match="no actor"):
            _with_source(actors=[])
        assert _with_source(actors=["member", "member"])["endpoints"][0]["actors"] == [
            "member"
        ]

    def test_a_parameter_cannot_be_a_secret(self):
        # A credential is supplied once and held in custody; it is never
        # restated as a query parameter.
        assert "secret" not in service_apps.PARAM_TYPES
        with pytest.raises(ListingDefinitionError, match="unknown field type"):
            _with_source(params=[{"key": "token", "type": "secret", "label": _label()}])


def _with_widget(**widget_overrides) -> dict:
    widget = {
        "id": "summary",
        "meta": {"name": {"en": "Sales summary"}},
        "module_source": "export const render = () => ({});",
    }
    widget.update(widget_overrides)
    return _normalize(features=["widgets"], widgets=[widget])


class TestWidgets:
    def test_a_widget_names_itself(self):
        with pytest.raises(ListingDefinitionError, match="meta must name"):
            _with_widget(meta={"description": {"en": "no name"}})

    def test_a_widget_ships_a_module(self):
        with pytest.raises(ListingDefinitionError, match="module_source is required"):
            _with_widget(module_source="")

    def test_a_module_larger_than_the_cap_is_refused(self):
        oversized = "x" * (service_apps.MAX_MODULE_SOURCE_BYTES + 1)
        with pytest.raises(ListingDefinitionError, match="larger than"):
            _with_widget(module_source=oversized)

    def test_a_module_is_stored_exactly_as_published(self):
        """Byte-for-byte: this build measures the module and stores it. What it
        contains is the browser sandbox's business, not this validator's."""
        source = "const render = (d) => ({ kind: 'metric', value: d.length });\n"
        definition = _with_widget(module_source=source)
        assert definition["widgets"][0]["module_source"] == source

    def test_a_widget_may_only_bind_an_endpoint_the_app_declares(self):
        with pytest.raises(
            ListingDefinitionError, match="not a declared read endpoint"
        ):
            _with_widget(endpoints=[READ_ID])

    def test_a_widget_may_only_bind_one_that_answers(self):
        # A write and an emission are both real endpoints and neither fills a
        # tile: one changes something and returns, the other is posted
        # somewhere else entirely.
        for direction in ("write", "emit"):
            with pytest.raises(
                ListingDefinitionError, match="not a declared read endpoint"
            ):
                _normalize(
                    features=["endpoints", "widgets"],
                    endpoints=[{"id": READ_ID, "direction": direction}],
                    widgets=[
                        {
                            "id": "summary",
                            "meta": {"name": {"en": "Sales summary"}},
                            "module_source": "export const render = () => ({});",
                            "endpoints": [READ_ID],
                        }
                    ],
                )

    def test_sample_rows_are_kept_only_for_declared_endpoints(self):
        definition = _normalize(
            features=["endpoints", "widgets"],
            endpoints=[{"id": READ_ID, "direction": "read"}],
            widgets=[
                {
                    "id": "summary",
                    "meta": {"name": {"en": "Sales summary"}},
                    "module_source": "export const render = () => ({});",
                    "endpoints": [READ_ID],
                    "sample_data": {
                        READ_ID: {"n": [1]},
                        "elsewhere": {"n": [2]},
                    },
                }
            ],
        )
        assert definition["widgets"][0]["sample_data"] == {READ_ID: {"n": [1]}}

    def test_a_sample_is_what_the_endpoint_would_answer(self):
        """An endpoint answers with its declared returns, so a sample is written
        in them too — the preview reads it the way the proxy reads a live one."""
        with pytest.raises(ListingDefinitionError, match="sample_data for"):
            _normalize(
                features=["endpoints", "widgets"],
                endpoints=[{"id": READ_ID, "direction": "read"}],
                widgets=[
                    {
                        "id": "summary",
                        "meta": {"name": {"en": "Sales summary"}},
                        "module_source": "export const render = () => ({});",
                        "endpoints": [READ_ID],
                        "sample_data": {READ_ID: [{"n": 1}]},
                    }
                ],
            )

    def test_sample_rows_are_size_capped(self):
        with pytest.raises(ListingDefinitionError, match="sample_data"):
            _normalize(
                features=["endpoints", "widgets"],
                endpoints=[{"id": READ_ID, "direction": "read"}],
                widgets=[
                    {
                        "id": "summary",
                        "meta": {"name": {"en": "Sales summary"}},
                        "module_source": "export const render = () => ({});",
                        "endpoints": [READ_ID],
                        "sample_data": {
                            READ_ID: {"blob": "x" * service_apps.MAX_SAMPLE_DATA_BYTES}
                        },
                    }
                ],
            )

    def test_two_widgets_cannot_share_an_id(self):
        widget = {
            "id": "summary",
            "meta": {"name": {"en": "Sales summary"}},
            "module_source": "export const render = () => ({});",
        }
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(features=["widgets"], widgets=[widget, dict(widget)])


class TestWidgetTypeNamespacing:
    def test_an_app_widget_carries_its_listing(self):
        assert app_widget_type("K7M2QX8N4TVB9C", "summary") == (
            "app:K7M2QX8N4TVB9C:summary"
        )

    def test_it_cannot_collide_with_a_built_in_type(self):
        from app.services.tenant.dashboard_definition import WIDGET_TYPES

        assert app_widget_type("K7M2QX8N4TVB9C", "stat") not in WIDGET_TYPES

    def test_the_separator_is_outside_the_id_alphabet(self):
        # Which is what keeps the three parts separable: no widget id can
        # contain the character that joins them.
        assert ":" not in IDENTIFIER_CHARS

    def test_a_widget_id_is_checked_before_it_is_composed(self):
        with pytest.raises(ListingDefinitionError, match="widget id"):
            app_widget_type("K7M2QX8N4TVB9C", "sum:mary")


class TestEmbeds:
    def _embed(self, **overrides) -> dict:
        embed = {
            "id": "orders",
            "path": "/embed/orders",
            "visibility": "guild_admin",
            "name": _label("Orders"),
        }
        embed.update(overrides)
        return _normalize(features=["embeds"], embeds=[embed])

    def test_an_embed_names_itself_for_the_sidebar(self):
        with pytest.raises(ListingDefinitionError, match="label"):
            self._embed(name=None)

    def test_an_embed_declares_a_path_not_an_address(self):
        with pytest.raises(ListingDefinitionError, match="path"):
            self._embed(path="https://widget.test/embed/orders")

    def test_an_embed_is_stored_canonically(self):
        definition = self._embed()
        assert definition["embeds"] == [
            {
                "id": "orders",
                "path": "/embed/orders",
                "scopes": ["guild"],
                "visibility": "guild_admin",
                "name": {"en": "Orders"},
            }
        ]


class TestWhatASurfaceMayAskItsFrameFor:
    """``capabilities`` is the whole of what a frame is granted.

    A manifest names browser features from a closed vocabulary, and a surface
    that names none is stored with no such key — which is what every definition
    pinned before this existed says, and what their frames now get.
    """

    def _embed(self, **overrides) -> dict:
        embed = {"id": "board", "path": "/embed", "name": _label("Board")}
        embed.update(overrides)
        return _normalize(features=["embeds"], embeds=[embed])["embeds"][0]

    def test_a_surface_asking_for_nothing_stores_nothing(self):
        assert "capabilities" not in self._embed()

    def test_a_surface_may_ask_for_what_it_needs(self):
        assert self._embed(capabilities=["clipboard-write"])["capabilities"] == [
            "clipboard-write"
        ]

    def test_capabilities_are_stored_canonically(self):
        """Sorted and de-duplicated, so re-publishing the same manifest produces
        the same document."""
        asked = ["fullscreen", "clipboard-write", "fullscreen"]
        assert self._embed(capabilities=asked)["capabilities"] == [
            "clipboard-write",
            "fullscreen",
        ]

    def test_a_capability_outside_the_vocabulary_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="not a capability"):
            self._embed(capabilities=["midi"])

    @pytest.mark.parametrize(
        "entry", [{"camera": True}, ["camera"], 7, None, True], ids=repr
    )
    def test_an_entry_that_is_not_a_name_is_refused(self, entry):
        """A publisher gets the same validation error for any entry that is not
        one of the names. Set membership is defined only for a hashable value,
        so an entry is typed before it is looked up rather than after."""
        with pytest.raises(ListingDefinitionError, match="not a capability"):
            self._embed(capabilities=[entry])

    def test_payment_is_not_namable(self):
        """The platform takes payment on its own pages, so an embedded surface
        has no reading of this to request."""
        assert "payment" not in EMBED_CAPABILITIES
        with pytest.raises(ListingDefinitionError, match="not a capability"):
            self._embed(capabilities=["payment"])


class TestWhereASurfaceRenders:
    """``scopes`` is not a choice between the two — it is a list.

    A surface may ask for the guild-wide entry, an entry in each initiative, or
    both; both is the interesting case, because it is one page reached from two
    places rather than two surfaces to keep in step.
    """

    def _embed(self, **overrides) -> dict:
        embed = {"id": "board", "path": "/embed", "name": _label("Board")}
        embed.update(overrides)
        return _normalize(features=["embeds"], embeds=[embed])["embeds"][0]

    def test_saying_nothing_keeps_the_placement_embeds_already_had(self):
        assert self._embed()["scopes"] == ["guild"]

    def test_a_surface_may_render_in_both(self):
        assert self._embed(scopes=["initiative", "guild"])["scopes"] == [
            "guild",
            "initiative",
        ]

    def test_a_surface_may_render_only_inside_initiatives(self):
        assert self._embed(scopes=["initiative"])["scopes"] == ["initiative"]

    def test_an_unknown_scope_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown scope"):
            self._embed(scopes=["project"])

    def test_nowhere_to_render_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="nowhere to render"):
            self._embed(scopes=[])

    def test_a_repeated_scope_is_stored_once(self):
        assert self._embed(scopes=["guild", "guild"])["scopes"] == ["guild"]


class TestVisibilityIsALadder:
    """A rung names the floor an audience clears, read against where it opens.

    The ordering is declared once so a manifest and a request cannot come to
    mean different things by the same word, and every rung is exercised here so
    adding one forces a decision rather than defaulting to "refused".
    """

    def _embed(self, **overrides) -> dict:
        embed = {
            "id": "board",
            "path": "/embed",
            "name": _label("Board"),
            "scopes": ["initiative"],
        }
        embed.update(overrides)
        return _normalize(features=["embeds"], embeds=[embed])["embeds"][0]

    def test_the_ladder_and_the_vocabulary_are_the_same_values(self):
        assert set(service_apps.VISIBILITY_LADDER) == service_apps.VISIBILITIES
        assert len(service_apps.VISIBILITY_LADDER) == len(service_apps.VISIBILITIES)

    @pytest.mark.parametrize("rung", service_apps.VISIBILITY_LADDER)
    def test_a_guild_admin_clears_every_rung(self, rung):
        assert service_apps.clears_visibility(rung, is_guild_admin=True)

    def test_a_member_clears_only_the_bottom_rung(self):
        assert service_apps.clears_visibility("member", is_guild_admin=False)
        assert not service_apps.clears_visibility(
            "initiative_manager", is_guild_admin=False
        )
        assert not service_apps.clears_visibility("guild_admin", is_guild_admin=False)

    def test_a_manager_clears_the_rung_named_for_them(self):
        assert service_apps.clears_visibility(
            "initiative_manager", is_guild_admin=False, is_initiative_manager=True
        )

    def test_managing_one_initiative_does_not_open_the_admin_rung(self):
        assert not service_apps.clears_visibility(
            "guild_admin", is_guild_admin=False, is_initiative_manager=True
        )

    def test_a_caller_with_no_initiative_in_hand_is_measured_without_it(self):
        # The guild-wide route: nobody is a manager of nothing, so the rung
        # falls through to the admins.
        assert not service_apps.clears_visibility(
            "initiative_manager", is_guild_admin=False
        )
        assert service_apps.clears_visibility("initiative_manager", is_guild_admin=True)

    @pytest.mark.parametrize("required", [None, "member"])
    def test_saying_nothing_admits_everyone_who_got_this_far(self, required):
        assert service_apps.clears_visibility(required, is_guild_admin=False)

    def test_a_value_this_build_does_not_know_is_refused(self):
        # Nothing stores one today; the predicate fails closed anyway, so a
        # rung added to the vocabulary and forgotten here denies rather than
        # admits.
        assert not service_apps.clears_visibility("everyone", is_guild_admin=False)

    def test_an_unknown_visibility_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown visibility"):
            self._embed(visibility="everyone")

    def test_an_initiative_surface_may_name_an_initiative_audience(self):
        assert self._embed(visibility="initiative_manager")["visibility"] == (
            "initiative_manager"
        )

    def test_a_guild_wide_surface_may_not(self):
        # There is nothing to manage out here, so the value would be stored as
        # a claim nothing could evaluate.
        with pytest.raises(ListingDefinitionError, match="initiative audience"):
            self._embed(scopes=["guild"], visibility="initiative_manager")

    def test_a_read_endpoint_may_not_either(self):
        with pytest.raises(ListingDefinitionError, match="initiative audience"):
            _with_source(visibility="initiative_manager")


class TestEmissions:
    def _emit(self, **overrides) -> dict:
        endpoint = {"id": "app.tests.widget-co.order-created", "direction": "emit"}
        endpoint.update(overrides)
        return _normalize(features=["endpoints"], endpoints=[endpoint])

    def test_an_id_is_namespaced_under_the_app(self):
        for value in ("order_created", "app.someone.else.order_created"):
            with pytest.raises(ListingDefinitionError, match="must start with"):
                self._emit(id=value)

    def test_the_namespace_alone_is_not_an_id(self):
        with pytest.raises(ListingDefinitionError, match="must start with"):
            self._emit(id="app.tests.widget-co.")

    def test_a_declared_one_is_kept(self):
        definition = self._emit()
        assert definition["endpoints"] == [
            {"id": "app.tests.widget-co.order-created", "direction": "emit"}
        ]

    def test_two_of_the_same_id_are_refused(self):
        # One id, two answers, and which one a caller reaches would depend on
        # iteration order.
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(
                features=["endpoints"],
                endpoints=[
                    {"id": "app.tests.widget-co.order-created", "direction": "emit"},
                    {"id": "app.tests.widget-co.order-created", "direction": "read"},
                ],
            )


class TestCanonicalShape:
    def test_unknown_keys_are_dropped(self):
        definition = _normalize(
            default_name="Widget Co",
            surprise="dropped",
            base_url="https://widget.test",
        )
        assert set(definition) == {
            "app_kind",
            "service",
            "features",
            "default_name",
        }

    def test_a_definition_holds_no_address_anywhere(self):
        """The governing rule, asserted on a manifest that tries: an app says
        which route, and the deployment's registration says where."""
        definition = _normalize(
            features=["endpoints", "embeds"],
            service={
                "public_id": "tests.widget-co",
                "protocol": 1,
                "default_url": "http://widget.test:8100",
            },
            connections=[
                {
                    "id": "shop",
                    "scope": "interactive",
                    "label": _label(),
                    "connect_path": "/connect/shop",
                }
            ],
            endpoints=[
                {"id": READ_ID, "direction": "read", "base_url": "http://x.test"}
            ],
            embeds=[
                {
                    "id": "orders",
                    "path": "/embed/orders",
                    "name": _label(),
                    "url": "https://widget.test/embed/orders",
                }
            ],
        )
        rendered = repr(definition)
        assert "http://" not in rendered
        assert "https://" not in rendered
        assert "default_url" not in definition["service"]

    def test_the_whole_document_is_size_capped(self):
        # Each widget is under the per-module cap; together they are not.
        module = "x" * (service_apps.MAX_MODULE_SOURCE_BYTES - 1)
        widgets = [
            {
                "id": f"w{index}",
                "meta": {"name": {"en": f"Widget {index}"}},
                "module_source": module,
            }
            for index in range(service_apps.MAX_WIDGETS)
        ]
        with pytest.raises(ListingDefinitionError, match="service app definition"):
            _normalize(features=["widgets"], widgets=widgets)

    def test_a_block_longer_than_its_cap_is_refused_not_truncated(self):
        with pytest.raises(ListingDefinitionError, match="more than"):
            _normalize(
                features=["embeds"],
                embeds=[
                    {"id": f"e{index}", "path": f"/embed/{index}", "name": _label()}
                    for index in range(service_apps.MAX_EMBEDS + 1)
                ],
            )


class TestWhatAnEndpointSaysItIs:
    """The half a consumer reads before it ever makes a call.

    A widget binds a column and an automation offers a value for a later step,
    and both have to be arrangeable — and refusable — before the endpoint has
    run once. None of it means anything to THIS build, which is the point:
    these are bounded and stored, never interpreted.
    """

    def test_a_label_and_description_are_kept(self):
        cleaned = _with_source(
            label=_label("Open issues"), description=_label("Everything still open")
        )
        endpoint = cleaned["endpoints"][0]
        assert endpoint["label"] == _label("Open issues")
        assert endpoint["description"] == _label("Everything still open")

    def test_an_emission_may_be_labelled_too(self):
        """The one endpoint chosen from a list without ever being called, so it
        needs a name more than the others do — and the branch that strips
        everything else from an emission must let it through."""
        cleaned = _normalize(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "app.tests.widget-co.order-created",
                    "direction": "emit",
                    "label": _label("An order is placed"),
                    "returns": [{"key": "order_id", "type": "int"}],
                    "group": "orders",
                }
            ],
        )
        endpoint = cleaned["endpoints"][0]
        assert endpoint["label"] == _label("An order is placed")
        assert endpoint["returns"] == [{"key": "order_id", "type": "int"}]
        assert endpoint["group"] == "orders"

    def test_an_emission_still_has_no_caller_side(self):
        with pytest.raises(ListingDefinitionError, match="no params"):
            _normalize(
                features=["endpoints"],
                endpoints=[
                    {
                        "id": "app.tests.widget-co.order-created",
                        "direction": "emit",
                        "label": _label("An order is placed"),
                        "params": [{"key": "x", "type": "string", "label": _label()}],
                    }
                ],
            )

    def test_saying_nothing_stores_nothing(self):
        """An absent label is absent, not an empty one — the same rule every
        other optional block here follows."""
        endpoint = _with_source()["endpoints"][0]
        for key in ("label", "description", "returns", "group", "needs_subject"):
            assert key not in endpoint


class TestReturns:
    def test_a_return_carries_a_key_a_type_and_optionally_a_label(self):
        cleaned = _with_source(
            returns=[
                {"key": "count", "type": "int", "label": _label("How many")},
                {"key": "url", "type": "url"},
            ]
        )
        assert cleaned["endpoints"][0]["returns"] == [
            {"key": "count", "type": "int", "label": _label("How many")},
            {"key": "url", "type": "url"},
        ]

    def test_several_values_are_flagged_rather_than_typed_apart(self):
        cleaned = _with_source(
            returns=[{"key": "labels", "type": "string", "list": True}]
        )
        assert cleaned["endpoints"][0]["returns"][0]["list"] is True

    def test_select_is_not_a_return_type(self):
        """A select is a CONTROL, and the value behind one is a string."""
        with pytest.raises(ListingDefinitionError, match="unknown type"):
            _with_source(returns=[{"key": "k", "type": "select"}])

    def test_a_credential_is_not_a_return_type_either(self):
        with pytest.raises(ListingDefinitionError, match="unknown type"):
            _with_source(returns=[{"key": "k", "type": "secret"}])

    def test_two_returns_may_not_share_a_key(self):
        with pytest.raises(ListingDefinitionError, match="share the key"):
            _with_source(
                returns=[{"key": "k", "type": "int"}, {"key": "k", "type": "string"}]
            )

    def test_a_return_needs_a_readable_key(self):
        with pytest.raises(ListingDefinitionError):
            _with_source(returns=[{"key": "Not An Id", "type": "int"}])


class TestWhatAParameterTakes:
    """A manifest describes the API, not the control a consumer draws for it.

    ``picker`` named one of an automation editor's own controls inside a third
    party's manifest, so an app could only ask for something that editor had
    already thought of — and a consumer that writes its own step needs no term
    here at all. What survives is what a caller cannot infer: whether to send
    one value or an array.
    """

    def test_a_param_may_take_several_values(self):
        cleaned = _with_source(
            params=[{"key": "ids", "type": "int", "label": _label(), "list": True}]
        )
        assert cleaned["endpoints"][0]["params"][0]["list"] is True

    def test_one_value_is_the_default(self):
        cleaned = _with_source(params=[{"key": "id", "type": "int", "label": _label()}])
        assert "list" not in cleaned["endpoints"][0]["params"][0]

    def test_a_connection_field_takes_one_credential(self):
        """An admin types a credential once; there is no list of them."""
        cleaned = _normalize(
            features=["endpoints"],
            connections=[
                {
                    "id": "shop",
                    "scope": "static",
                    "label": _label(),
                    "fields": [
                        {
                            "key": "token",
                            "type": "secret",
                            "label": _label(),
                            "list": True,
                        }
                    ],
                }
            ],
            endpoints=[{"id": READ_ID, "direction": "read"}],
        )
        assert "list" not in cleaned["connections"][0]["fields"][0]


LOOKUP_ID = "app.tests.widget-co.boards"


def _with_option_source(source: dict, *, siblings: list | None = None) -> dict:
    """A read whose parameter draws its values from a second read."""
    return _normalize(
        features=["endpoints"],
        endpoints=[
            {
                "id": LOOKUP_ID,
                "direction": "read",
                "returns": [
                    {"key": "ids", "type": "string", "list": True},
                    {"key": "names", "type": "string", "list": True},
                    {"key": "total", "type": "int"},
                ],
                "params": [{"key": "owner", "type": "string", "label": _label()}],
            },
            {
                "id": READ_ID,
                "direction": "read",
                "params": (siblings or [])
                + [
                    {
                        "key": "board",
                        "type": "string",
                        "label": _label(),
                        "options_from": source,
                    }
                ],
            },
        ],
    )


class TestWhereAParametersValuesComeFrom:
    """Values a manifest cannot list because only the app can enumerate them.

    A repository, a channel, a board: the set differs per install and changes
    after it, so a parameter names the read that answers instead of carrying the
    answers. Every part of that reference is checked here, where every endpoint
    is known — a source that resolves to nothing fails silently at the far end,
    in a form that draws an empty menu.
    """

    def test_a_source_survives_a_publish_whole(self):
        cleaned = _with_option_source(
            {
                "endpoint": LOOKUP_ID,
                "key": "ids",
                "label_key": "names",
                "needs": {"owner": "org"},
            },
            siblings=[{"key": "org", "type": "string", "label": _label()}],
        )
        board = cleaned["endpoints"][1]["params"][1]
        assert board["options_from"] == {
            "endpoint": LOOKUP_ID,
            "key": "ids",
            "label_key": "names",
            "needs": {"owner": "org"},
        }

    def test_it_may_name_a_source_it_sends_nothing_to(self):
        cleaned = _with_option_source({"endpoint": LOOKUP_ID, "key": "ids"})
        assert "needs" not in cleaned["endpoints"][1]["params"][0]["options_from"]

    def test_an_endpoint_from_another_app_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="not declared here"):
            _with_option_source({"endpoint": "app.other.co.boards", "key": "ids"})

    def test_a_write_cannot_fill_in_a_form(self):
        with pytest.raises(ListingDefinitionError, match="does not read"):
            _normalize(
                features=["endpoints"],
                endpoints=[
                    {"id": LOOKUP_ID, "direction": "write"},
                    {
                        "id": READ_ID,
                        "direction": "read",
                        "params": [
                            {
                                "key": "board",
                                "type": "string",
                                "label": _label(),
                                "options_from": {"endpoint": LOOKUP_ID, "key": "ids"},
                            }
                        ],
                    },
                ],
            )

    def test_a_key_the_source_does_not_return_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="is not returned by"):
            _with_option_source({"endpoint": LOOKUP_ID, "key": "nope"})

    def test_one_value_cannot_be_a_menu(self):
        with pytest.raises(ListingDefinitionError, match="is a single value"):
            _with_option_source({"endpoint": LOOKUP_ID, "key": "total"})

    def test_it_can_only_send_a_parameter_the_source_takes(self):
        with pytest.raises(ListingDefinitionError, match="does not take"):
            _with_option_source(
                {"endpoint": LOOKUP_ID, "key": "ids", "needs": {"nope": "org"}},
                siblings=[{"key": "org", "type": "string", "label": _label()}],
            )

    def test_it_cannot_ask_for_the_answer_being_filled_in(self):
        with pytest.raises(ListingDefinitionError, match="being filled in"):
            _with_option_source(
                {"endpoint": LOOKUP_ID, "key": "ids", "needs": {"owner": "board"}}
            )

    def test_a_sibling_this_endpoint_does_not_declare_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="does not declare"):
            _with_option_source(
                {"endpoint": LOOKUP_ID, "key": "ids", "needs": {"owner": "org"}}
            )
