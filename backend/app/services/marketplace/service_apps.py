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

from typing import Any, Optional

from app.services.marketplace.manifest_values import (
    MAX_HINT_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_NAME_LENGTH,
    check_identifier,
    check_json_size,
    check_path,
    check_public_id,
    check_uid,
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
    "ACTOR_KINDS",
    "APP_PROTOCOL_VERSIONS",
    "APP_WIDGET_TYPE_PREFIX",
    "WIDGET_BINDABLE_DIRECTIONS",
    "CONNECTION_SCOPES",
    "DIRECTIONS",
    "EMBED_CAPABILITIES",
    "FEATURES",
    "FEATURE_BLOCKS",
    "FIELD_TYPES",
    "GUILD_WIDE_VISIBILITIES",
    "PARAM_TYPES",
    "SURFACE_SCOPES",
    "VISIBILITIES",
    "VISIBILITY_LADDER",
    "app_widget_type",
    "clears_visibility",
    "normalize_service_app_definition",
]

# --- vocabulary -------------------------------------------------------------

#: Which block backs each feature. The single source for the cross-check that
#: keeps a declaration and a manifest body from disagreeing — and, below, for
#: the vocabulary itself.
FEATURE_BLOCKS: dict[str, str] = {
    "endpoints": "endpoints",
    "widgets": "widgets",
    "embeds": "embeds",
    "dashboards": "dashboards",
}

#: Capability classes an app can contribute. Closed: a manifest naming anything
#: else is refused rather than stored as a claim nothing can act on.
#:
#: Derived rather than restated. A feature with no block behind it is exactly
#: what :func:`_check_features` refuses, so a second list could only ever be
#: wrong — and was, until a feature was added to one of them.
FEATURES: frozenset[str] = frozenset(FEATURE_BLOCKS)

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

#: Where a surface renders. Not a choice between the two: a surface may declare
#: either, or both, and one that declares both gets a guild-wide entry *and* an
#: entry inside each initiative — the same page, told which initiative it was
#: opened in. Closed, and defaulting to ``["guild"]``, so an app that says
#: nothing keeps the placement it already had.
SURFACE_SCOPES: frozenset[str] = frozenset({"guild", "initiative"})

#: Who may open a surface, in order. A ladder rather than a set: a value names
#: the floor an audience has to clear, and each rung clears the ones below it.
#: ``guild_admin`` is the guild's admins, who clear every rung — an admin's
#: reach over their own guild is the same rule here as it is everywhere else.
#:
#: A rung is read against *where* the surface was opened, which is what lets one
#: value serve a surface in both scopes:
#:
#: * ``member`` guild-wide is every member of the installing guild; inside an
#:   initiative it is that initiative's members, and no one else's — the
#:   initiative gate is what answers that, not a claim in a manifest.
#: * ``initiative_manager`` inside an initiative is that initiative's managers;
#:   guild-wide, where there is no initiative to manage, only the guild's
#:   admins reach it.
#:
#: Deliberately coarser than a tool's permissions. A surface has no grants and
#: no permission key to hang a per-role dial on, so it names one of three
#: audiences rather than an arbitrary initiative role.
VISIBILITY_LADDER: tuple[str, ...] = ("member", "initiative_manager", "guild_admin")
VISIBILITIES: frozenset[str] = frozenset(VISIBILITY_LADDER)

#: The rungs something opened without an initiative may ask for.
#: ``initiative_manager`` is absent: outside an initiative there is nothing to
#: manage, so the value would be stored as a claim nothing could ever evaluate.
GUILD_WIDE_VISIBILITIES: frozenset[str] = VISIBILITIES - {"initiative_manager"}

#: Browser features an embedded surface may ask its frame for.
#:
#: A frame is granted nothing it did not name here, so an app that says nothing
#: gets a frame with every one of these denied. The vocabulary is closed for the
#: same reason every other one in this module is: a value outside it is refused
#: with a reason rather than stored as a request nothing resolves.
#:
#: These are Permissions-Policy feature names, and what a manifest asks for is
#: what a guild admin is shown at install. ``payment`` is deliberately not
#: namable — an embedded surface takes no money, and the platform processes
#: payments on its own pages.
EMBED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "camera",
        "clipboard-read",
        "clipboard-write",
        "display-capture",
        "fullscreen",
        "geolocation",
        "microphone",
    }
)

#: No surface has a use for the whole vocabulary at once; a manifest reaching
#: this many is describing something other than an embedded page.
MAX_EMBED_CAPABILITIES = 8

#: Protocol versions this build speaks to an app service. A manifest naming a
#: newer one is refused by name — the version floor (`min_app_version`) is how a
#: publisher says "this needs a newer Initiative".
APP_PROTOCOL_VERSIONS: frozenset[int] = frozenset({1})

#: Widget type ids from an app are namespaced, so an app's widget can never
#: resolve to a built-in renderer (or the other way round). ``:`` is outside the
#: identifier character set, so the three parts stay separable.
APP_WIDGET_TYPE_PREFIX = "app:"

#: Every endpoint an app declares is namespaced under its own service id.
ENDPOINT_ID_PREFIX = "app."
ENDPOINT_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

#: Which way a call across an endpoint travels.
#:
#: ``read`` and ``write`` are both request/response and differ only in whether
#: the caller expects the app to change something at its vendor — which decides
#: whether an answer may be cached. ``emit`` is the other direction: a
#: subscriber registers a URL and the app posts to it, so there is nothing to
#: call and nothing to cache.
#:
#: An endpoint belongs to no particular consumer. A widget reads one, an
#: automation reads or calls the same one, and a subscriber waits on a third —
#: they are peers, and the direction describes the endpoint rather than who is
#: allowed to want it.
DIRECTIONS: frozenset[str] = frozenset({"read", "write", "emit"})

#: Which of those a **widget** may bind — a rule about the tile, not about the
#: endpoint. A widget draws what it is given, so it can only bind one that
#: answers; nothing constrains an automation the same way.
WIDGET_BINDABLE_DIRECTIONS: frozenset[str] = frozenset({"read"})

#: Whose credential an endpoint runs on. The app resolves it; this is the
#: vocabulary it states its preference in, best first.
ACTOR_KINDS: frozenset[str] = frozenset({"member", "installation"})

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
MAX_WIDGET_ENDPOINTS = 8
#: Reads, writes and emissions share one list, so this bounds all three
#: together rather than each separately.
MAX_ENDPOINTS = 64
MAX_PARAMS_PER_ENDPOINT = 12
MAX_EMBEDS = 12
#: An app ships a handful of arrangements of its own widgets, not a library of
#: them. Each becomes a catalog row, so this is also how many listings a single
#: publish can create.
MAX_BUNDLED_DASHBOARDS = 8
#: The dashboard tool's own limits, restated rather than imported: this is the
#: manifest vocabulary, and the tool validates the derived definition again on
#: its own terms when an instance is created from it.
MAX_DASHBOARD_WIDGETS = 50
MAX_DASHBOARD_GRID_COLUMNS = 12
MAX_DASHBOARD_BINDING_PARAMS = 12
#: One line under a bundled dashboard's name. Matches the catalog column it
#: becomes, so a description that publishes here fits the row it derives.
MAX_DESCRIPTION_LENGTH = 500
#: A fixed parameter value on a tile's binding.
MAX_PARAM_VALUE_LENGTH = 2_000
MAX_ENDPOINT_ID_LENGTH = 200
#: A day. A read that wants a longer memory than that is asking for a stale
#: dashboard rather than a cheaper one.
MAX_CACHE_TTL_SECONDS = 86_400

#: A widget's browser-side module. Never parsed here — only measured.
MAX_MODULE_SOURCE_BYTES = 64 * 1024
#: Rows powering a preview with no network call.
MAX_SAMPLE_DATA_BYTES = 32 * 1024
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


def _visibility(raw: Any, *, what: str, allowed: frozenset[str] = VISIBILITIES) -> str:
    """One rung of the ladder, or the default.

    ``allowed`` narrows it for something with no initiative to name, so a value
    is refused where it could not be evaluated rather than stored and quietly
    read as something else later.
    """
    if raw is None:
        return "member"
    if raw not in VISIBILITIES:
        fail(f"{what}: unknown visibility {raw!r}")
    if raw not in allowed:
        fail(
            f"{what}: visibility {raw!r} names an initiative audience, and this "
            "surface is not opened in an initiative"
        )
    return raw


def clears_visibility(
    required: Any,
    *,
    is_guild_admin: bool,
    is_initiative_manager: bool = False,
) -> bool:
    """Whether a caller reaches something declaring ``required``.

    The ladder's ordering is written once, here, so what a manifest may declare
    and what a request is measured against cannot drift apart. A caller with no
    initiative in hand leaves ``is_initiative_manager`` false and is measured on
    the rungs that remain. Anything unrecognized is refused.
    """
    if is_guild_admin:
        return True
    if required is None or required == "member":
        return True
    if required == "initiative_manager":
        return is_initiative_manager
    return False


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


def _endpoint_id(raw: Any, *, service_public_id: str, what: str) -> str:
    """One endpoint id, namespaced under the app's own service id.

    The prefix is checked here and again at ingress against the declaring
    registration, so an app can answer and announce only under its own name. Two
    apps offering ``create-issue`` would be two different things under one name,
    and a caller that resolved the wrong one would do the wrong thing
    successfully — which is worse than an error.
    """
    prefix = f"{ENDPOINT_ID_PREFIX}{service_public_id}."
    if not isinstance(raw, str) or not raw:
        fail(f"{what} is required")
    if len(raw) > MAX_ENDPOINT_ID_LENGTH:
        fail(f"{what} {raw[:40]!r}… is too long")
    for character in raw:
        if character not in ENDPOINT_ID_CHARS:
            fail(f"{what} {raw!r} contains {character!r}")
    if not raw.startswith(prefix) or len(raw) == len(prefix):
        fail(f"{what} {raw!r} must start with {prefix!r}")
    return raw


def _endpoint(
    raw: Any, *, connection_ids: set[str], service_public_id: str
) -> dict[str, Any]:
    """One thing the app will do when something connects to it.

    A single vocabulary for every caller and every direction. A widget filling a
    tile, an automation service asking the app to act, and a subscriber waiting
    to be told all name an id from this list, and what separates them is which
    token they prove themselves with rather than which route they found.

    The id is the address. There is no path to choose, so two apps cannot answer
    the same question at different URLs and a caller that knows the id needs
    nothing else to make the call.
    """
    endpoint = require_mapping(raw, "endpoint")
    endpoint_id = _endpoint_id(
        endpoint.get("id"), service_public_id=service_public_id, what="endpoint id"
    )
    what = f"endpoint {endpoint_id!r}"

    direction = endpoint.get("direction")
    if direction not in DIRECTIONS:
        fail(f"{what}: direction must be one of {sorted(DIRECTIONS)}")

    params_raw = require_list(
        endpoint.get("params"), f"{what} params", MAX_PARAMS_PER_ENDPOINT
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

    cleaned: dict[str, Any] = {"id": endpoint_id, "direction": direction}

    # An emission travels the other way: nobody calls it, so there is nothing
    # for a caller to send, nothing to cache and nobody to gate. Carrying any of
    # it would describe a call that never happens.
    if direction == "emit":
        for absent in (
            "params",
            "requires",
            "cache_ttl_seconds",
            "visibility",
            "actors",
        ):
            if endpoint.get(absent) is not None:
                fail(f"{what}: an emit endpoint has no {absent}")
        return cleaned

    if params:
        cleaned["params"] = params

    actors = _actors(endpoint.get("actors"), what=what)
    if actors:
        cleaned["actors"] = actors

    # Only a read is answered from cache, and only a read is reached by an
    # audience wide enough to need a rung. A write is authorized by the token
    # that carried it.
    if direction == "read":
        # A read is answered for a guild, not for an initiative, so the rungs
        # that need one are not on offer here.
        cleaned["visibility"] = _visibility(
            endpoint.get("visibility"), what=what, allowed=GUILD_WIDE_VISIBILITIES
        )
        cleaned["cache_ttl_seconds"] = _cache_ttl(
            endpoint.get("cache_ttl_seconds"), what=what
        )
    else:
        for absent in ("cache_ttl_seconds", "visibility"):
            if endpoint.get(absent) is not None:
                fail(f"{what}: only a read endpoint has {absent}")

    requires = _requires(
        endpoint.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _actors(raw: Any, *, what: str) -> list[str]:
    """Whose credential the app will run this on, best first.

    A list rather than a set because the order is the app's preference, and a
    caller reads it to know what it is asking for: an endpoint offering only
    ``member`` refuses when the member has connected nothing, rather than
    quietly acting as the app instead.
    """
    if raw is None:
        return []
    declared = require_list(raw, f"{what} actors", len(ACTOR_KINDS))
    actors: list[str] = []
    for entry in declared:
        if entry not in ACTOR_KINDS:
            fail(f"{what}: actors must be drawn from {sorted(ACTOR_KINDS)}")
        if entry not in actors:
            actors.append(entry)
    if not actors:
        fail(f"{what}: names no actor it could run as")
    return actors


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
    raw: Any, *, readable_ids: set[str], connection_ids: set[str]
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

    bound = require_list(
        widget.get("endpoints"), f"{what} endpoints", MAX_WIDGET_ENDPOINTS
    )
    endpoints: list[str] = []
    for entry in bound:
        if not isinstance(entry, str) or entry not in readable_ids:
            # Named rather than described: a write and an emission are both real
            # endpoints, and neither fills a tile, so "unknown" would be the
            # wrong word for the mistake somebody is most likely making.
            fail(f"{what}: binds {entry!r}, which is not a declared read endpoint")
        if entry not in endpoints:
            endpoints.append(entry)

    cleaned: dict[str, Any] = {
        "id": widget_id,
        "meta": meta,
        "module_source": module_source,
    }
    if endpoints:
        cleaned["endpoints"] = endpoints

    sample = _sample_data(widget.get("sample_data"), sources=endpoints, what=what)
    if sample:
        cleaned["sample_data"] = sample
    requires = _requires(
        widget.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


def _bundled_dashboard(
    raw: Any, *, widget_ids: set[str], readable_ids: set[str]
) -> dict[str, Any]:
    """One dashboard an app ships with itself.

    A publisher who declares widgets otherwise leaves every guild to arrange
    them. This is a ready-made arrangement of *this app's own* widgets, which
    becomes an ordinary ``dashboard`` catalog listing when the app is published —
    so a guild installs it the same way it installs any other dashboard, and
    what it gets afterwards is an ordinary dashboard of its own.

    Two things make it different from a dashboard published on its own, and both
    are why it can be checked here at all:

    * **It names widgets by bare id.** A manifest has no uid inside it — the uid
      lives in the document envelope — so widget types are resolved to
      ``app:<uid>:<widget id>`` at publish, exactly as
      :func:`app_widget_type` already does for the palette. The publisher never
      writes a uid into a widget type, so the two cannot disagree.
    * **It can only reference this manifest.** Every widget and every bound
      source is checked against what the same document declares, so a bundled
      dashboard cannot name a widget the app does not have — the failure a
      separately published dashboard can only hit at install, and silently.

    The ``uid`` and ``public_id`` are the publisher's own, and are what make the
    derived row a real catalog identity rather than something invented here.
    """
    entry = require_mapping(raw, "bundled dashboard")
    uid = check_uid(entry.get("uid"), what="bundled dashboard uid")
    public_id = check_public_id(
        entry.get("public_id"), what=f"bundled dashboard {uid} public_id"
    )
    what = f"bundled dashboard {public_id!r}"

    name = clean_text(entry.get("name"), what=f"{what} name", limit=MAX_NAME_LENGTH)
    if not name:
        fail(f"{what}: name is required")
    description = clean_text(
        entry.get("description"),
        what=f"{what} description",
        limit=MAX_DESCRIPTION_LENGTH,
        required=False,
    )

    widgets = [
        _bundled_dashboard_widget(
            widget, widget_ids=widget_ids, readable_ids=readable_ids, what=what
        )
        for widget in require_list(
            entry.get("widgets"), f"{what} widgets", MAX_DASHBOARD_WIDGETS
        )
    ]
    if not widgets:
        fail(f"{what}: a dashboard with no widgets shows nothing")

    seen: set[str] = set()
    for widget in widgets:
        if widget["id"] in seen:
            fail(f"{what}: two widgets share the id {widget['id']!r}")
        seen.add(widget["id"])

    cleaned: dict[str, Any] = {
        "uid": uid,
        "public_id": public_id,
        "name": name,
        "widgets": widgets,
    }
    if description is not None:
        cleaned["description"] = description

    columns = _grid_int(
        (entry.get("layout") or {}).get("columns")
        if isinstance(entry.get("layout"), dict)
        else None,
        low=1,
        high=MAX_DASHBOARD_GRID_COLUMNS,
        what=f"{what} layout.columns",
    )
    if columns is not None:
        cleaned["layout"] = {"columns": columns}
    return cleaned


def _bundled_dashboard_widget(
    raw: Any, *, widget_ids: set[str], readable_ids: set[str], what: str
) -> dict[str, Any]:
    """One tile, naming one of this app's widgets and one of its sources."""
    widget = require_mapping(raw, f"{what} widget")
    widget_type = check_identifier(widget.get("type"), what=f"{what} widget type")
    if widget_type not in widget_ids:
        fail(f"{what}: names unknown widget {widget_type!r}")

    binding = require_mapping(widget.get("binding"), f"{what} widget binding")
    endpoint_id = binding.get("endpoint_id")
    if not isinstance(endpoint_id, str) or endpoint_id not in readable_ids:
        fail(f"{what}: binds {endpoint_id!r}, which is not a declared read endpoint")

    bound: dict[str, Any] = {"endpoint_id": endpoint_id}
    params = binding.get("params")
    if params is not None:
        bound["params"] = _bundled_binding_params(params, what=what)

    cleaned: dict[str, Any] = {
        # Defaulted from the widget it draws, so a publisher who ships one tile
        # per widget writes no ids at all.
        "id": check_identifier(
            widget.get("id") or widget_type, what=f"{what} widget id"
        ),
        "type": widget_type,
        "binding": bound,
    }

    title = clean_text(
        widget.get("title"),
        what=f"{what} widget title",
        limit=MAX_NAME_LENGTH,
        required=False,
    )
    if title is not None:
        cleaned["title"] = title

    grid = widget.get("grid")
    if isinstance(grid, dict):
        placed = {
            key: _grid_int(
                grid.get(key),
                low=0 if key in ("x", "y") else 1,
                high=MAX_DASHBOARD_GRID_COLUMNS if key in ("x", "w") else None,
                what=f"{what} widget grid.{key}",
            )
            for key in ("x", "y", "w", "h")
        }
        kept = {key: value for key, value in placed.items() if value is not None}
        if kept:
            cleaned["grid"] = kept
    return cleaned


def _bundled_binding_params(raw: Any, *, what: str) -> dict[str, Any]:
    """Fixed parameter values for a tile's source. Scalars, kept as they are.

    Deliberately not coerced: the source's ``params_schema`` declares the type,
    and turning a ``true`` into a ``1`` here would satisfy a check the fetch path
    is meant to make.
    """
    params = require_mapping(raw, f"{what} widget binding params")
    if len(params) > MAX_DASHBOARD_BINDING_PARAMS:
        fail(f"{what}: a binding carries at most {MAX_DASHBOARD_BINDING_PARAMS} params")
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        name = check_identifier(key, what=f"{what} binding param")
        if isinstance(value, bool) or isinstance(value, int):
            cleaned[name] = value
        elif isinstance(value, str):
            cleaned[name] = clean_text(
                value, what=f"{what} binding param {name}", limit=MAX_PARAM_VALUE_LENGTH
            )
        else:
            fail(f"{what}: binding param {name!r} must be a string, integer or boolean")
    return cleaned


def _grid_int(raw: Any, *, low: int, high: Optional[int], what: str) -> Optional[int]:
    """A grid coordinate, or ``None`` when the publisher left it to the canvas."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        fail(f"{what} must be a whole number")
    if raw < low or (high is not None and raw > high):
        bound = f"{low}..{high}" if high is not None else f"at least {low}"
        fail(f"{what} must be {bound}")
    return raw


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


def _scopes(raw: Any, *, what: str) -> list[str]:
    """Where a surface asked to render, canonically.

    Absent means ``["guild"]`` — the placement every embed had before there was
    anywhere else to put one. Sorted and de-duplicated, so re-publishing the
    same manifest produces the same document.
    """
    if raw is None:
        return ["guild"]
    declared = require_list(raw, f"{what} scopes", len(SURFACE_SCOPES))
    scopes: set[str] = set()
    for entry in declared:
        if entry not in SURFACE_SCOPES:
            fail(f"{what}: unknown scope {entry!r}")
        scopes.add(entry)
    if not scopes:
        fail(f"{what}: scopes names nowhere to render")
    return sorted(scopes)


def _capabilities(raw: Any, *, what: str) -> list[str]:
    """The browser features a surface asks its frame for.

    Absent means none, which is also what a frame gets when the manifest names
    nothing. Sorted and de-duplicated, so re-publishing the same manifest
    produces the same document.
    """
    if raw is None:
        return []
    declared = require_list(raw, f"{what} capabilities", MAX_EMBED_CAPABILITIES)
    capabilities: set[str] = set()
    for entry in declared:
        # Typed before it is looked up: set membership is defined only for a
        # hashable value, so a name is what this compares.
        if not isinstance(entry, str) or entry not in EMBED_CAPABILITIES:
            fail(
                f"{what}: {entry!r} is not a capability a surface may request "
                f"(one of {', '.join(sorted(EMBED_CAPABILITIES))})"
            )
        capabilities.add(entry)
    return sorted(capabilities)


def _embed(raw: Any, *, connection_ids: set[str]) -> dict[str, Any]:
    embed = require_mapping(raw, "embed")
    embed_id = check_identifier(embed.get("id"), what="embed id")
    what = f"embed {embed_id!r}"

    scopes = _scopes(embed.get("scopes"), what=what)
    cleaned: dict[str, Any] = {
        "id": embed_id,
        "path": check_path(embed.get("path"), what=f"{what} path"),
        "scopes": scopes,
        "visibility": _visibility(
            embed.get("visibility"),
            what=what,
            # An initiative audience is only namable by a surface that renders
            # in one.
            allowed=(
                VISIBILITIES if "initiative" in scopes else GUILD_WIDE_VISIBILITIES
            ),
        ),
        "name": _label(embed.get("name"), what=what),
    }
    capabilities = _capabilities(embed.get("capabilities"), what=what)
    if capabilities:
        cleaned["capabilities"] = capabilities
    requires = _requires(
        embed.get("requires"), connection_ids=connection_ids, what=what
    )
    if requires is not None:
        cleaned["requires"] = requires
    return cleaned


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

    # One list for every direction, so a caller resolves an id without being
    # told which kind of thing it is first.
    endpoints = [
        _endpoint(
            entry,
            connection_ids=connection_ids,
            service_public_id=service["public_id"],
        )
        for entry in require_list(
            body.get("endpoints"), "service app: endpoints", MAX_ENDPOINTS
        )
    ]
    endpoint_ids: set[str] = set()
    readable_ids: set[str] = set()
    for endpoint in endpoints:
        if endpoint["id"] in endpoint_ids:
            fail(f"service app: two endpoints share the id {endpoint['id']!r}")
        endpoint_ids.add(endpoint["id"])
        if endpoint["direction"] in WIDGET_BINDABLE_DIRECTIONS:
            readable_ids.add(endpoint["id"])

    widgets = [
        _widget(entry, readable_ids=readable_ids, connection_ids=connection_ids)
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
    if endpoints:
        cleaned["endpoints"] = endpoints
    if widgets:
        cleaned["widgets"] = widgets
    if embeds:
        cleaned["embeds"] = embeds

    # After the widgets and endpoints it can name, because every tile is checked
    # against them — the whole point of bundling rather than publishing
    # separately is that this cross-check is possible at all.
    dashboards = [
        _bundled_dashboard(entry, widget_ids=widget_ids, readable_ids=readable_ids)
        for entry in require_list(
            body.get("dashboards"), "service app: dashboards", MAX_BUNDLED_DASHBOARDS
        )
    ]
    if dashboards:
        seen_uids: set[str] = set()
        seen_public_ids: set[str] = set()
        for dashboard in dashboards:
            # Checked here as well as by the catalog: these become listing rows
            # whose identities are unique, and a manifest that collides with
            # itself would fail halfway through a publish.
            if dashboard["uid"] in seen_uids:
                fail(f"service app: two dashboards share the uid {dashboard['uid']}")
            if dashboard["public_id"] in seen_public_ids:
                fail(
                    "service app: two dashboards share the public_id "
                    f"{dashboard['public_id']!r}"
                )
            if dashboard["public_id"] == service["public_id"]:
                fail(
                    f"service app: dashboard {dashboard['uid']} uses the app's own "
                    "public_id; a bundled dashboard is its own listing"
                )
            seen_uids.add(dashboard["uid"])
            seen_public_ids.add(dashboard["public_id"])
        cleaned["dashboards"] = dashboards

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
