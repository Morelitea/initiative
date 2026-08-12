"""Service apps: what a manifest may declare, and nothing else.

A ``service`` app is one whose features are realized by a container the operator
runs. Its definition is the widest thing this build accepts from a publisher, so
it is also the strictest: a closed vocabulary, an explicit cap on every string,
list and opaque body, and unknown keys dropped rather than stored.

Three properties hold by construction, and they are why a definition is safe to
keep and later hand to a guild:

* **It names capabilities, not addresses.** Every route an app offers is a
  *path*; the base URL comes from a deployment-level registration. There is
  nowhere in here to put a host.
* **Nothing in it runs here.** ``module_source`` is a widget's browser-side
  module: it is measured and stored as an opaque string, and this build has no
  path that parses, compiles, imports, or evaluates it. The browser's sandbox is
  the only thing that ever executes it.
* **Blocks this build assigns no meaning to stay opaque.** The ``automation``
  body belongs to the automation service; it is checked for shape and size and
  passed through verbatim, with no vocabulary here describing its contents.

Features are the app's own statement of what it contributes, and they are
cross-checked against the blocks present in both directions so the statement
cannot drift from the manifest. They inform install dialogs, deployment-fit
messaging, and review — they never gate installation. An app may declare no
local features at all: an integration that exists to give an external system a
foothold in a guild is a legitimate install with nothing to render.
"""

from __future__ import annotations

from typing import Any

from app.services.marketplace.manifest_values import (
    MAX_HINT_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_NAME_LENGTH,
    check_identifier,
    check_json_size,
    check_path,
    check_public_id,
    clean_text,
    fail,
    require_list,
    require_mapping,
    utf8_bytes,
)
from app.services.marketplace.widget_meta import (
    MAX_TEXT_LENGTH,
    localized_text,
    validate_widget_meta,
)

__all__ = [
    "APP_PROTOCOL_VERSIONS",
    "APP_WIDGET_TYPE_PREFIX",
    "CONNECTION_SCOPES",
    "FEATURES",
    "FEATURE_BLOCKS",
    "FIELD_TYPES",
    "PARAM_TYPES",
    "VISIBILITIES",
    "app_widget_type",
    "normalize_service_app_definition",
]

# --- vocabulary -------------------------------------------------------------

#: Capability classes an app can contribute. Closed: a manifest naming anything
#: else is refused rather than stored as a claim nothing can act on.
FEATURES: frozenset[str] = frozenset(
    {"data", "widgets", "embeds", "events", "automations"}
)

#: Which block backs each feature. The single source for the cross-check that
#: keeps a declaration and a manifest body from disagreeing.
FEATURE_BLOCKS: dict[str, str] = {
    "data": "data_sources",
    "widgets": "widgets",
    "embeds": "embeds",
    "events": "events",
    "automations": "automation",
}

#: Who supplies a connection's credential, which decides its scope.
#:
#: ``static`` — a guild admin types it in, and the whole guild uses it.
#: ``interactive`` — the app runs a vendor flow behind its ``connect_path`` and
#: each member connects their own account.
CONNECTION_SCOPES: frozenset[str] = frozenset({"static", "interactive"})

#: Field kinds a connection form can render. The same closed enum the automation
#: service's node contract settled on, so one generic form renderer draws every
#: app's settings page.
FIELD_TYPES: frozenset[str] = frozenset(
    {"string", "secret", "url", "bool", "select", "int"}
)

#: What a data source may take as a query parameter. ``secret`` is absent: a
#: parameter travels with a request, and credentials are supplied once, held in
#: custody, and never restated per call.
PARAM_TYPES: frozenset[str] = FIELD_TYPES - {"secret"}

#: Who may open a surface. ``member`` is any member of the installing guild;
#: ``guild_admin`` narrows it to the guild's admins.
VISIBILITIES: frozenset[str] = frozenset({"member", "guild_admin"})

#: Protocol versions this build speaks to an app service. A manifest naming a
#: newer one is refused by name — the version floor (`min_app_version`) is how a
#: publisher says "this needs a newer Initiative".
APP_PROTOCOL_VERSIONS: frozenset[int] = frozenset({1})

#: Widget type ids from an app are namespaced, so an app's widget can never
#: resolve to a built-in renderer (or the other way round). ``:`` is outside the
#: identifier character set, so the three parts stay separable.
APP_WIDGET_TYPE_PREFIX = "app:"

#: Every event an app emits is namespaced under its own service id.
EVENT_TYPE_PREFIX = "app."
EVENT_TYPE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

# --- caps -------------------------------------------------------------------
#
# Counts first, then bodies. Together they bound what one published version can
# weigh: the per-item caps bound a single widget or blob, and the whole-document
# cap bounds the sum, so no combination of legal parts adds up to an illegal
# document.

MAX_CONNECTIONS = 20
MAX_FIELDS_PER_CONNECTION = 12
MAX_SELECT_OPTIONS = 24
MAX_ACCESS_HINT_SCOPES = 24
MAX_REQUIRES_TERMS = 10
MAX_WIDGETS = 12
MAX_WIDGET_SOURCES = 8
MAX_DATA_SOURCES = 24
MAX_PARAMS_PER_SOURCE = 12
MAX_EMBEDS = 12
MAX_EVENTS = 50
MAX_EVENT_TYPE_LENGTH = 200
#: A day. A source that wants a longer memory than that is asking for a stale
#: dashboard rather than a cheaper one.
MAX_CACHE_TTL_SECONDS = 86_400

#: A widget's browser-side module. Never parsed here — only measured.
MAX_MODULE_SOURCE_BYTES = 64 * 1024
#: Rows powering a preview with no network call.
MAX_SAMPLE_DATA_BYTES = 32 * 1024
#: The automation service's own block, stored verbatim.
MAX_AUTOMATION_BYTES = 64 * 1024
#: The canonical definition, after normalization. Checked last, so a publisher
#: is told the document is too large rather than which cap they happened to hit
#: first.
MAX_SERVICE_DEFINITION_BYTES = 512 * 1024


# --- shared pieces ----------------------------------------------------------


def _label(raw: Any, *, what: str, max_length: int = MAX_TEXT_LENGTH) -> dict[str, str]:
    """A localized label, read by the same rules a widget's own strings are.

    One rule for every human-readable string an app supplies, so an app names
    its connections in as many languages as it names its widgets.
    """
    label = localized_text(raw, max_length)
    if label is None:
        fail(f"{what} must carry a label with at least one language")
    return label


def _requires(
    raw: Any, *, connection_ids: set[str], what: str
) -> dict[str, Any] | None:
    """Which connections satisfy an item.

    One level, one operator: ``all_of`` or ``any_of`` over connection ids, or
    absent for "always available". Satisfaction is later evaluated from the
    presence of values alone — this build never inspects a credential — so the
    only thing checkable here is that every id names a connection the manifest
    actually declares.
    """
    if raw is None:
        return None
    requires = require_mapping(raw, f"{what} requires")
    named = [key for key in ("all_of", "any_of") if key in requires]
    if len(named) != 1:
        fail(f"{what}: requires must name exactly one of 'all_of' or 'any_of'")
    key = named[0]
    terms = require_list(requires[key], f"{what} requires.{key}", MAX_REQUIRES_TERMS)
    cleaned: list[str] = []
    for term in terms:
        connection_id = check_identifier(term, what=f"{what} requires.{key} entry")
        if connection_id not in connection_ids:
            fail(f"{what}: requires names unknown connection {connection_id!r}")
        if connection_id not in cleaned:
            cleaned.append(connection_id)
    if not cleaned:
        fail(f"{what}: requires.{key} names no connection")
    return {key: cleaned}


def _visibility(raw: Any, *, what: str) -> str:
    if raw is None:
        return "member"
    if raw not in VISIBILITIES:
        fail(f"{what}: unknown visibility {raw!r}")
    return raw


def _field(
    raw: Any,
    *,
    types: frozenset[str],
    allow_managed: bool,
    what: str,
) -> dict[str, Any]:
    """One typed input, in a connection form or a data source's parameters."""
    field = require_mapping(raw, what)
    key = check_identifier(field.get("key"), what=f"{what} key")
    field_type = field.get("type")
    if field_type not in types:
        fail(f"{what} {key!r}: unknown field type {field_type!r}")

    cleaned: dict[str, Any] = {
        "key": key,
        "type": field_type,
        "required": field.get("required") is True,
        "label": _label(field.get("label"), what=f"{what} {key!r}"),
    }
    if field_type == "select":
        options = require_list(
            field.get("options"), f"{what} {key!r} options", MAX_SELECT_OPTIONS
        )
        values = [
            clean_text(option, what=f"{what} {key!r} option", limit=MAX_LABEL_LENGTH)
            for option in options
        ]
        if not values:
            fail(f"{what} {key!r}: a select field must offer at least one option")
        cleaned["options"] = values
    # Keys the app writes back itself, rather than the admin typing them: an
    # interactive flow returns its result through the app's own write path.
    if allow_managed and field.get("managed") is True:
        cleaned["managed"] = True
    return cleaned


# --- connections ------------------------------------------------------------


def _access_hint(raw: Any, *, what: str) -> dict[str, Any] | None:
    """What a connection says it will use the credential for.

    Display-only truth in advertising: the settings form names the API and the
    permissions the app wants, so an admin can mint a minimal credential. No
    other system's permissions can be enforced from here, and none is claimed
    to be — this only makes least privilege the visible default.
    """
    if raw is None:
        return None
    hint = require_mapping(raw, f"{what} access_hint")
    cleaned: dict[str, Any] = {}
    api = clean_text(
        hint.get("api"),
        what=f"{what} access_hint.api",
        limit=MAX_HINT_LENGTH,
        required=False,
    )
    if api is not None:
        cleaned["api"] = api
    scopes = require_list(
        hint.get("scopes"), f"{what} access_hint.scopes", MAX_ACCESS_HINT_SCOPES
    )
    named = [
        clean_text(scope, what=f"{what} access_hint.scope", limit=MAX_HINT_LENGTH)
        for scope in scopes
    ]
    if named:
        cleaned["scopes"] = named
    return cleaned or None


def _connection(raw: Any) -> dict[str, Any]:
    connection = require_mapping(raw, "connection")
    connection_id = check_identifier(connection.get("id"), what="connection id")
    what = f"connection {connection_id!r}"

    scope = connection.get("scope")
    if scope not in CONNECTION_SCOPES:
        fail(f"{what}: unknown scope {scope!r}")

    fields_raw = require_list(
        connection.get("fields"), f"{what} fields", MAX_FIELDS_PER_CONNECTION
    )
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in fields_raw:
        field = _field(
            entry, types=FIELD_TYPES, allow_managed=True, what=f"{what} field"
        )
        if field["key"] in seen:
            fail(f"{what}: two fields share the key {field['key']!r}")
        seen.add(field["key"])
        fields.append(field)

    cleaned: dict[str, Any] = {
        "id": connection_id,
        "scope": scope,
        "label": _label(connection.get("label"), what=what),
        "fields": fields,
    }

    if scope == "static" and not fields:
        # Nothing for the admin to supply, so nothing this connection could be.
        fail(f"{what}: a static connection must declare at least one field")

    connect_path = connection.get("connect_path")
    if scope == "interactive":
        # The route the member is sent to so the app can run the vendor's flow.
        cleaned["connect_path"] = check_path(connect_path, what=f"{what} connect_path")
    elif connect_path is not None:
        fail(f"{what}: only an interactive connection has a connect_path")

    hint = _access_hint(connection.get("access_hint"), what=what)
    if hint is not None:
        cleaned["access_hint"] = hint
    return cleaned


# --- what an app offers -----------------------------------------------------


def _data_source(raw: Any, *, connection_ids: set[str]) -> dict[str, Any]:
    source = require_mapping(raw, "data source")
    source_id = check_identifier(source.get("id"), what="data source id")
    what = f"data source {source_id!r}"

    params_raw = require_list(
        source.get("params_schema"), f"{what} params_schema", MAX_PARAMS_PER_SOURCE
    )
    params: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in params_raw:
        param = _field(
            entry, types=PARAM_TYPES, allow_managed=False, what=f"{what} param"
        )
        if param["key"] in seen:
            fail(f"{what}: two parameters share the key {param['key']!r}")
        seen.add(param["key"])
        params.append(param)

    cleaned: dict[str, Any] = {
        "id": source_id,
        "path": check_path(source.get("path"), what=f"{what} path"),
        "visibility": _visibility(source.get("visibility"), what=what),
        "cache_ttl_seconds": _cache_ttl(source.get("cache_ttl_seconds"), what=what),
    }
    if params:
        cleaned["params_schema"] = params
    requires = _requires(
        source.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _cache_ttl(raw: Any, *, what: str) -> int:
    """How long a response may be reused. Clamped rather than refused: a number
    out of range is a judgement about freshness, not a vocabulary this build
    cannot resolve."""
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, int):
        fail(f"{what}: cache_ttl_seconds must be a whole number of seconds")
    return max(0, min(raw, MAX_CACHE_TTL_SECONDS))


def _widget(
    raw: Any, *, source_ids: set[str], connection_ids: set[str]
) -> dict[str, Any]:
    widget = require_mapping(raw, "widget")
    widget_id = check_identifier(widget.get("id"), what="widget id")
    what = f"widget {widget_id!r}"

    meta = validate_widget_meta(widget.get("meta"))
    if meta is None:
        fail(f"{what}: meta must name the widget in at least one language")

    module_source = widget.get("module_source")
    if not isinstance(module_source, str) or not module_source.strip():
        fail(f"{what}: module_source is required")
    # Measured, never read: the module is a string to this build, and the
    # browser's sandbox is the only thing that evaluates it.
    encoded = utf8_bytes(module_source, what=f"{what} module_source")
    if len(encoded) > MAX_MODULE_SOURCE_BYTES:
        fail(f"{what}: module_source is larger than {MAX_MODULE_SOURCE_BYTES} bytes")

    bound = require_list(widget.get("sources"), f"{what} sources", MAX_WIDGET_SOURCES)
    sources: list[str] = []
    for entry in bound:
        source_id = check_identifier(entry, what=f"{what} source")
        if source_id not in source_ids:
            fail(f"{what}: binds unknown data source {source_id!r}")
        if source_id not in sources:
            sources.append(source_id)

    cleaned: dict[str, Any] = {
        "id": widget_id,
        "meta": meta,
        "module_source": module_source,
    }
    if sources:
        cleaned["sources"] = sources

    sample = _sample_data(widget.get("sample_data"), sources=sources, what=what)
    if sample:
        cleaned["sample_data"] = sample
    requires = _requires(
        widget.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _sample_data(raw: Any, *, sources: list[str], what: str) -> dict[str, Any]:
    """Rows that let a preview render with no network call at all.

    Keyed by the sources the widget declared; anything else is dropped, so a
    sample cannot describe data the widget could never be handed. The rows
    themselves are opaque — this build stores them for the browser to pass into
    a render, and reads nothing out of them.
    """
    if raw is None:
        return {}
    supplied = require_mapping(raw, f"{what} sample_data")
    allowed = set(sources)
    sample = {key: value for key, value in supplied.items() if key in allowed}
    check_json_size(sample, what=f"{what} sample_data", limit=MAX_SAMPLE_DATA_BYTES)
    return sample


def _embed(raw: Any, *, connection_ids: set[str]) -> dict[str, Any]:
    embed = require_mapping(raw, "embed")
    embed_id = check_identifier(embed.get("id"), what="embed id")
    what = f"embed {embed_id!r}"

    cleaned: dict[str, Any] = {
        "id": embed_id,
        "path": check_path(embed.get("path"), what=f"{what} path"),
        "visibility": _visibility(embed.get("visibility"), what=what),
        "name": _label(embed.get("name"), what=what),
    }
    requires = _requires(
        embed.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _events(raw: Any, *, service_public_id: str) -> list[str]:
    """Event types the app emits, namespaced under its own service id.

    The prefix is checked here and again at ingress against the emitting
    registration, so an app can announce and emit only under its own name.
    """
    prefix = f"{EVENT_TYPE_PREFIX}{service_public_id}."
    declared = require_list(raw, "events", MAX_EVENTS)
    events: list[str] = []
    for entry in declared:
        if not isinstance(entry, str) or not entry:
            fail("events must be a list of event type names")
        if len(entry) > MAX_EVENT_TYPE_LENGTH:
            fail(f"event type {entry[:40]!r}… is too long")
        for character in entry:
            if character not in EVENT_TYPE_CHARS:
                fail(f"event type {entry!r} contains {character!r}")
        if not entry.startswith(prefix) or len(entry) == len(prefix):
            fail(f"event type {entry!r} must start with {prefix!r}")
        if entry not in events:
            events.append(entry)
    return events


def _automation(raw: Any) -> dict[str, Any] | None:
    """The automation service's own block.

    Opaque by design: this build checks that it is a JSON object within a size
    cap and stores it verbatim. It holds no vocabulary describing what is inside
    — descriptor shapes, triggers, and execution belong to the service that owns
    automations, and duplicating any of it here would be a second definition of
    a contract this repository does not own.
    """
    if raw is None:
        return None
    automation = require_mapping(raw, "automation")
    check_json_size(automation, what="automation", limit=MAX_AUTOMATION_BYTES)
    return automation


# --- the definition ---------------------------------------------------------


def app_widget_type(listing_uid: str, widget_id: str) -> str:
    """The type id a listing's widget is offered under.

    Namespaced with the catalog uid, so two apps can both ship a ``summary``
    widget and neither can shadow a built-in type. ``:`` is outside the
    identifier character set, so the parts stay unambiguous — and the id is
    re-checked here, so that stays true wherever this is called from.
    """
    check_identifier(widget_id, what="widget id")
    return f"{APP_WIDGET_TYPE_PREFIX}{listing_uid}:{widget_id}"


def _service_block(raw: Any) -> dict[str, Any]:
    service = require_mapping(raw, "service app: service")
    public_id = check_public_id(
        service.get("public_id"), what="service app: service.public_id"
    )
    protocol = service.get("protocol", 1)
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        fail("service app: service.protocol must be a whole number")
    if protocol not in APP_PROTOCOL_VERSIONS:
        fail(
            f"service app: protocol {protocol} is not one this build speaks "
            f"({sorted(APP_PROTOCOL_VERSIONS)})"
        )
    return {"public_id": public_id, "protocol": protocol}


def _features(raw: Any) -> list[str]:
    declared = require_list(raw, "service app: features", len(FEATURES))
    features: set[str] = set()
    for entry in declared:
        if entry not in FEATURES:
            fail(f"service app: unknown feature {entry!r}")
        features.add(entry)
    # Sorted, so a re-publish of the same manifest produces the same document.
    return sorted(features)


def _check_features(features: list[str], cleaned: dict[str, Any]) -> None:
    """Both directions, because either mismatch is a manifest that lies.

    A feature declared with no block behind it would advertise something the app
    cannot do; a block with no feature declared would ship a capability the
    install dialog never disclosed and review never looked at.
    """
    declared = set(features)
    for feature, block in FEATURE_BLOCKS.items():
        # Membership, not truthiness: whether a block was stored is the question,
        # and reading it as a value would let a stored-but-empty block count as
        # absent here while still being persisted.
        present = block in cleaned
        if feature in declared and not present:
            fail(
                f"service app: the {feature!r} feature is declared but "
                f"{block} is missing"
            )
        if present and feature not in declared:
            fail(
                f"service app: {block} is present but the {feature!r} feature "
                "is not declared"
            )


def normalize_service_app_definition(definition: Any) -> dict[str, Any]:
    """Validate and canonicalize a service app's definition."""
    body = require_mapping(definition, "service app definition")

    service = _service_block(body.get("service"))

    connections = [
        _connection(entry)
        for entry in require_list(
            body.get("connections"), "service app: connections", MAX_CONNECTIONS
        )
    ]
    connection_ids: set[str] = set()
    for connection in connections:
        if connection["id"] in connection_ids:
            fail(f"service app: two connections share the id {connection['id']!r}")
        connection_ids.add(connection["id"])

    data_sources = [
        _data_source(entry, connection_ids=connection_ids)
        for entry in require_list(
            body.get("data_sources"), "service app: data_sources", MAX_DATA_SOURCES
        )
    ]
    source_ids: set[str] = set()
    for source in data_sources:
        if source["id"] in source_ids:
            fail(f"service app: two data sources share the id {source['id']!r}")
        source_ids.add(source["id"])

    widgets = [
        _widget(entry, source_ids=source_ids, connection_ids=connection_ids)
        for entry in require_list(
            body.get("widgets"), "service app: widgets", MAX_WIDGETS
        )
    ]
    widget_ids: set[str] = set()
    for widget in widgets:
        if widget["id"] in widget_ids:
            fail(f"service app: two widgets share the id {widget['id']!r}")
        widget_ids.add(widget["id"])

    embeds = [
        _embed(entry, connection_ids=connection_ids)
        for entry in require_list(body.get("embeds"), "service app: embeds", MAX_EMBEDS)
    ]
    embed_ids: set[str] = set()
    for embed in embeds:
        if embed["id"] in embed_ids:
            fail(f"service app: two embeds share the id {embed['id']!r}")
        embed_ids.add(embed["id"])

    cleaned: dict[str, Any] = {
        "app_kind": "service",
        "service": service,
        "features": _features(body.get("features")),
    }
    # Empty blocks are left out entirely, so "does this app offer widgets?" has
    # one answer rather than two shapes that mean the same thing.
    if connections:
        cleaned["connections"] = connections
    if data_sources:
        cleaned["data_sources"] = data_sources
    if widgets:
        cleaned["widgets"] = widgets
    if embeds:
        cleaned["embeds"] = embeds

    events = _events(body.get("events"), service_public_id=service["public_id"])
    if events:
        cleaned["events"] = events
    automation = _automation(body.get("automation"))
    # Same rule as every block above: an empty one is left out rather than
    # stored as a second way of saying "none". An automation block that is
    # present but empty describes nothing, and storing it would let a manifest
    # carry a block its `features` never declared.
    if automation:
        cleaned["automation"] = automation

    default_name = clean_text(
        body.get("default_name"),
        what="service app: default_name",
        limit=MAX_NAME_LENGTH,
        required=False,
    )
    if default_name is not None:
        cleaned["default_name"] = default_name

    _check_features(cleaned["features"], cleaned)
    check_json_size(
        cleaned,
        what="service app definition",
        limit=MAX_SERVICE_DEFINITION_BYTES,
    )
    return cleaned
