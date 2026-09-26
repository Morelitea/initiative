"""What a guild-app read payload discloses.

Two properties, pulling in opposite directions, and both are load-bearing.

**The pinned definition travels.** A reader — the settings page, and an
installed app reading its own install — has to be able to say what *this*
install is, including the blocks this build assigns no meaning to. Serving the
snapshot the guild pinned rather than whatever the catalog holds today is what
makes that answer true of the install rather than of the listing.

**Stored values never do.** The definition describes the form; what was typed
into it lives in columns this payload does not read. Serializing one alongside
the other would be the single most natural way to leak a credential, so the test
reads the whole payload rather than checking the field somebody remembered.
"""

from datetime import datetime, timezone
from types import SimpleNamespace


from app.db.guild_standing import GuildContext
from app.models.platform.guild import Guild
from app.schemas.tenant.guild_app import serialize_guild_app


SECRET_DIGEST = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"

DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": "tests.shop", "protocol": 1},
    "features": ["events", "automations"],
    "connections": [
        {
            "id": "admin",
            "scope": "static",
            "fields": [{"key": "admin_token", "type": "secret", "required": True}],
        }
    ],
    "events": ["app.tests.shop.order_created"],
    # Opaque to this build by design: it belongs to the automation service,
    # which parses it off this same payload.
    "automation": {"nodes": [{"id": "low_stock"}]},
}


#: The standing a request in this app's community carries, which is what the
#: serializer names the community from. Built here because these payloads are
#: built without a request.
CONTEXT = GuildContext(
    guild=Guild(id=7, name="g"),
    user_id=11,
    guild_id=7,
    standing_guild_id=7,
)


def _app(**overrides) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        **{
            "id": 3,
            "guild_id": 7,
            "listing_uid": "TESTAPP0000001",
            "listing_version": "1.2.0",
            "app_kind": "service",
            "name": "Shop",
            "enabled": True,
            # Tracking its listing, which is what an install that never opted
            # out says and what the serializer reads.
            "auto_update": True,
            "definition": DEFINITION,
            "config": {},
            "secret_fields": {"admin": {"admin_token": SECRET_DIGEST}},
            "config_state": "ok",
            "config_state_detail": None,
            "granted_scopes": [],
            "created_by": 11,
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
    )


def test_the_pinned_definition_is_passed_through_verbatim():
    payload = serialize_guild_app(_app(), context=CONTEXT)

    assert payload.definition == DEFINITION
    # Including the block this build never interprets — an app reads it here
    # rather than through an endpoint that would have to understand it.
    assert payload.definition["automation"] == {"nodes": [{"id": "low_stock"}]}


def test_the_config_state_the_app_reported_is_carried():
    """Until an app reports, an install has no verdict; once it does, the
    settings page can say whether the app is happy without leaving the app."""
    assert serialize_guild_app(_app(), context=CONTEXT).config_state == "ok"
    assert (
        serialize_guild_app(
            _app(config_state="invalid", config_state_detail="missing_read_orders"),
            context=CONTEXT,
        ).config_state_detail
        == "missing_read_orders"
    )
    assert serialize_guild_app(
        _app(config_state="unverified"), context=CONTEXT
    ).config_state == ("unverified")


def test_no_stored_value_appears_anywhere_in_the_payload():
    payload = serialize_guild_app(
        _app(config={"admin": {"shop_domain": "example.test"}}), context=CONTEXT
    )

    serialized = payload.model_dump_json()
    assert SECRET_DIGEST not in serialized
    assert "secret_fields" not in serialized
    # The definition describes the field; it carries no value for it.
    assert payload.definition["connections"][0]["fields"][0]["key"] == "admin_token"
    assert "value" not in payload.definition["connections"][0]["fields"][0]


def test_needs_config_still_reads_from_presence():
    """A required guild-wide field with nothing in it is the one thing this
    build can know by itself, and it is unaffected by the passthrough."""
    assert (
        serialize_guild_app(_app(secret_fields={}), context=CONTEXT).needs_config
        is True
    )
    assert serialize_guild_app(_app(), context=CONTEXT).needs_config is False


def test_placements_are_the_rows_handed_in_ordered_by_initiative():
    """The serializer reads no placement off the install: the caller loads the
    rows, once for a whole list."""
    rows = [
        SimpleNamespace(initiative_id=9, role_ids=[4]),
        SimpleNamespace(initiative_id=2, role_ids=[]),
    ]
    payload = serialize_guild_app(_app(), context=CONTEXT, placements=rows)

    assert [p.model_dump() for p in payload.placements] == [
        {"initiative_id": 2, "role_ids": []},
        {"initiative_id": 9, "role_ids": [4]},
    ]
    assert serialize_guild_app(_app(), context=CONTEXT).placements == []


def test_granted_scopes_are_reported_sorted_and_empty_by_default():
    """What the seat consented to reads back as a set in one order, and an
    install nobody has granted anything holds nothing."""
    assert serialize_guild_app(_app(), context=CONTEXT).granted_scopes == []
    payload = serialize_guild_app(
        _app(granted_scopes=["projects:write", "comments:read"]), context=CONTEXT
    )
    assert payload.granted_scopes == ["comments:read", "projects:write"]


def test_surface_access_is_computed_for_the_viewer():
    """Each declared surface, with where this viewer opens it: the placement's
    roles inside an initiative, admins alone at the community level and on an
    ``admin_only`` surface."""
    definition = {
        **DEFINITION,
        "embeds": [
            {"id": "board", "path": "/b", "scopes": ["guild", "initiative"]},
            {
                "id": "settings",
                "path": "/s",
                "scopes": ["initiative"],
                "admin_only": True,
            },
        ],
    }
    rows = [
        SimpleNamespace(initiative_id=2, role_ids=[40]),
        SimpleNamespace(initiative_id=5, role_ids=[41]),
    ]
    member = GuildContext(
        guild=Guild(id=7, name="g"),
        user_id=12,
        guild_id=7,
        standing_guild_id=7,
        member_role_ids=(40,),
    )
    admin = GuildContext(
        guild=Guild(id=7, name="g"),
        user_id=11,
        guild_id=7,
        standing_guild_id=7,
        admin=True,
    )

    def access(context):
        payload = serialize_guild_app(
            _app(definition=definition), context=context, placements=rows
        )
        return {one.surface_id: one.model_dump() for one in payload.surface_access}

    assert access(member) == {
        "board": {
            "surface_id": "board",
            "openable_guild_wide": False,
            "openable_initiatives": [2],
        },
        "settings": {
            "surface_id": "settings",
            "openable_guild_wide": False,
            "openable_initiatives": [],
        },
    }
    assert access(admin) == {
        "board": {
            "surface_id": "board",
            "openable_guild_wide": True,
            "openable_initiatives": [2, 5],
        },
        "settings": {
            "surface_id": "settings",
            "openable_guild_wide": False,
            "openable_initiatives": [2, 5],
        },
    }
