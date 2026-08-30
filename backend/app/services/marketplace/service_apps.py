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

from app.services.marketplace import contract
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

#: Capability classes an app can contribute. Closed: a manifest naming anything
#: else is refused rather than stored as a claim nothing can act on.
FEATURES: frozenset[str] = contract.enum("feature")

#: Which block backs each feature. The single source for the cross-check that
#: keeps a declaration and a manifest body from disagreeing.
#:
#: Derived rather than restated: a feature and its block share a name, so a
#: second list could only ever be missing one — and was, until a feature was
#: added to one of them.
FEATURE_BLOCKS: dict[str, str] = {feature: feature for feature in sorted(FEATURES)}

#: Whose credential a connection holds — not how it is obtained.
#:
#: ``static`` — one credential the whole guild uses.
#: ``interactive`` — each member's own account at a vendor that authorizes
#: people, and never anybody else's.
#:
#: A ``connect_path`` is the second question, asked of either: with one, the app
#: runs the vendor's flow, and the scope decides who is sent — every member for
#: their own account, or a guild admin once, for the guild. Without one, a
#: static connection is a form an admin types into. Some vendors leave no
#: choice: an organization-wide install is a page at the vendor with a button
#: on it, and no string an admin retypes here is the same thing.
CONNECTION_SCOPES: frozenset[str] = contract.enum("connectionScope")

#: Field kinds a connection form can render. The same closed enum the automation
#: service's node contract settled on, so one generic form renderer draws every
#: app's settings page.
FIELD_TYPES: frozenset[str] = contract.enum("fieldType")

#: What a data source may take as a query parameter. ``secret`` is absent: a
#: parameter travels with a request, and credentials are supplied once, held in
#: custody, and never restated per call.
PARAM_TYPES: frozenset[str] = contract.enum("paramType")

#: Where a surface renders. Not a choice between the two: a surface may declare
#: either, or both, and one that declares both gets a guild-wide entry *and* an
#: entry inside each initiative — the same page, told which initiative it was
#: opened in. Closed, and defaulting to ``["guild"]``, so an app that says
#: nothing keeps the placement it already had.
SURFACE_SCOPES: frozenset[str] = contract.enum("surfaceScope")

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
VISIBILITY_LADDER: tuple[str, ...] = contract.ladder("visibility")
VISIBILITIES: frozenset[str] = frozenset(VISIBILITY_LADDER)

#: The rungs something opened without an initiative may ask for.
#: ``initiative_manager`` is absent: outside an initiative there is nothing to
#: manage, so the value would be stored as a claim nothing could ever evaluate.
GUILD_WIDE_VISIBILITIES: frozenset[str] = contract.enum("endpointVisibility")

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
EMBED_CAPABILITIES: frozenset[str] = contract.enum("embedCapability")

#: No surface has a use for the whole vocabulary at once; a manifest reaching
#: this many is describing something other than an embedded page.
MAX_EMBED_CAPABILITIES = contract.cap("embedCapabilities")

#: Protocol versions this build speaks to an app service. A manifest naming a
#: newer one is refused by name — the version floor (`min_app_version`) is how a
#: publisher says "this needs a newer Initiative".
APP_PROTOCOL_VERSIONS: frozenset[int] = contract.int_enum("protocol")

#: Widget type ids from an app are namespaced, so an app's widget can never
#: resolve to a built-in renderer (or the other way round). ``:`` is outside the
#: identifier character set, so the three parts stay separable.
APP_WIDGET_TYPE_PREFIX = "app:"

#: Every endpoint an app declares is namespaced under its own service id.
ENDPOINT_ID_PREFIX = "app."
ENDPOINT_ID_CHARS = contract.charset("namespacedId")

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
DIRECTIONS: frozenset[str] = contract.enum("direction")

#: Which of those a **widget** may bind — a rule about the tile, not about the
#: endpoint. A widget draws what it is given, so it can only bind one that
#: answers; nothing constrains an automation the same way.
WIDGET_BINDABLE_DIRECTIONS: frozenset[str] = frozenset({"read"})

#: Whose credential an endpoint runs on. The app resolves it; this is the
#: vocabulary it states its preference in, best first.
ACTOR_KINDS: frozenset[str] = contract.enum("actorKind")

#: What an endpoint may say it hands BACK — the param vocabulary minus
#: ``select``, because a select is a *control* and the value behind one is a
#: string. Nothing here is a credential for the same reason a param is not.
#:
#: A caller reads these to know what it can do with an answer before it has
#: one: the automation service offers them as values a later step may bind, and
#: it has to be able to refuse a bad binding when somebody SAVES rather than
#: when the thing eventually runs.
RETURN_TYPES: frozenset[str] = contract.enum("returnValueType")

# --- caps -------------------------------------------------------------------
#
# Counts first, then bodies. Together they bound what one published version can
# weigh: the per-item caps bound a single widget or blob, and the whole-document
# cap bounds the sum, so no combination of legal parts adds up to an illegal
# document.

MAX_CONNECTIONS = contract.cap("connections")
MAX_FIELDS_PER_CONNECTION = contract.cap("fieldsPerConnection")
MAX_SELECT_OPTIONS = contract.cap("selectOptions")
MAX_ACCESS_HINT_SCOPES = contract.cap("accessHintScopes")
MAX_REQUIRES_TERMS = contract.cap("requiresTerms")
MAX_WIDGETS = contract.cap("widgets")
MAX_WIDGET_ENDPOINTS = contract.cap("widgetEndpoints")
#: Reads, writes and emissions share one list, so this bounds all three
#: together rather than each separately.
MAX_ENDPOINTS = contract.cap("endpoints")
MAX_PARAMS_PER_ENDPOINT = contract.cap("paramsPerEndpoint")
#: What one endpoint may name as coming back. Higher than the param cap on
#: purpose: describing an answer is cheaper than asking for one, and an app
#: that returns a dozen fields is ordinary where one taking a dozen is not.
MAX_RETURNS_PER_ENDPOINT = contract.cap("returnsPerEndpoint")
MAX_EMBEDS = contract.cap("embeds")
#: An app ships a handful of arrangements of its own widgets, not a library of
#: them. Each becomes a catalog row, so this is also how many listings a single
#: publish can create.
MAX_BUNDLED_DASHBOARDS = contract.cap("bundledDashboards")
#: The dashboard tool's own limits, restated rather than imported: this is the
#: manifest vocabulary, and the tool validates the derived definition again on
#: its own terms when an instance is created from it.
MAX_DASHBOARD_WIDGETS = contract.cap("dashboardWidgets")
MAX_DASHBOARD_GRID_COLUMNS = contract.cap("dashboardGridColumns")
MAX_DASHBOARD_BINDING_PARAMS = contract.cap("dashboardBindingParams")
#: One line under a bundled dashboard's name. Matches the catalog column it
#: becomes, so a description that publishes here fits the row it derives.
MAX_DESCRIPTION_LENGTH = contract.cap("descriptionLength")
#: A fixed parameter value on a tile's binding.
MAX_PARAM_VALUE_LENGTH = contract.cap("paramValueLength")
MAX_ENDPOINT_ID_LENGTH = contract.cap("endpointIdLength")
#: A day. A read that wants a longer memory than that is asking for a stale
#: dashboard rather than a cheaper one.
MAX_CACHE_TTL_SECONDS = contract.cap("cacheTtlSeconds")
#: Returns that may be joined into one address. An address, not a record.
MAX_IDENTITY_KEY_PARTS = contract.cap("identityKeyParts")

#: A widget's browser-side module. Never parsed here — only measured.
MAX_MODULE_SOURCE_BYTES = contract.cap("moduleSourceBytes")
#: Rows powering a preview with no network call.
MAX_SAMPLE_DATA_BYTES = contract.cap("sampleDataBytes")
#: The canonical definition, after normalization. Checked last, so a publisher
#: is told the document is too large rather than which cap they happened to hit
#: first.
MAX_SERVICE_DEFINITION_BYTES = contract.cap("serviceDefinitionBytes")


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
    allow_list: bool = False,
) -> dict[str, Any]:
    """One typed input, in a connection form or an endpoint's parameters.

    ``allow_list`` is what separates the two. A connection's field is a single
    credential an admin types; an endpoint's parameter may take several values,
    and the caller has to be told which.
    """
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
    # Cardinality is a fact about the value rather than about a control, so it
    # is the app's to state and a caller has to know it: whether to send one
    # value or an array is not something a consumer can infer.
    if allow_list and field.get("list") is True:
        cleaned["list"] = True

    # Where the permitted values come from, when only the app can know them.
    # `options` is the other case: a set that is the same on every deployment.
    if allow_list:
        source = _options_from(field.get("options_from"), what=f"{what} {key!r}")
        if source is not None:
            cleaned["options_from"] = source
    # Keys the app writes back itself, rather than the admin typing them: a
    # vendor flow returns its result through the app's own write path.
    if allow_managed and field.get("managed") is True:
        cleaned["managed"] = True
    return cleaned


def _options_from(raw: Any, *, what: str) -> dict[str, Any] | None:
    """Where a parameter's values come from, as a reference and nothing more.

    A repository, a channel, a board, a project: values that differ per install,
    change after it, and can only be enumerated by the app holding that
    install's credential. None of them can be written into a manifest, which is
    published once and is identical on every deployment — so a parameter names
    the read endpoint that answers instead.

    Shape only here. That the endpoint exists, reads rather than writes, and
    returns the keys named is checked where every endpoint is known, the same
    way a widget's binding is.
    """
    if raw is None:
        return None

    source = require_mapping(raw, f"{what} options_from")
    named = source.get("endpoint")
    if not isinstance(named, str) or not named:
        fail(f"{what} options_from endpoint is required")
    if len(named) > MAX_ENDPOINT_ID_LENGTH:
        fail(f"{what} options_from endpoint {named[:40]!r}… is too long")
    for character in named:
        if character not in ENDPOINT_ID_CHARS:
            fail(f"{what} options_from endpoint {named!r} contains {character!r}")

    cleaned: dict[str, Any] = {
        "endpoint": named,
        "key": check_identifier(source.get("key"), what=f"{what} options_from key"),
    }

    label_key = source.get("label_key")
    if label_key is not None:
        cleaned["label_key"] = check_identifier(
            label_key, what=f"{what} options_from label_key"
        )

    needs = source.get("needs")
    if needs is not None:
        cleaned["needs"] = _option_source_needs(needs, what=what)
    return cleaned


def _option_source_needs(raw: Any, *, what: str) -> dict[str, str]:
    """What to send that endpoint, in its parameter names and this one's.

    Past the first source in a form, most of them answer differently depending
    on what has been chosen already — a repository's labels, a board's fields, a
    field's values — so a source names the sibling answers it needs.

    Shape only here. That each side names a real parameter is checked where
    every endpoint is known, the same way the endpoint itself is.
    """
    supplied = require_mapping(raw, f"{what} options_from needs")
    if len(supplied) > MAX_PARAMS_PER_ENDPOINT:
        fail(
            f"{what} options_from names more than "
            f"{MAX_PARAMS_PER_ENDPOINT} parameters to send"
        )
    needs: dict[str, str] = {}
    for theirs, ours in supplied.items():
        key = check_identifier(theirs, what=f"{what} options_from needs key")
        needs[key] = check_identifier(ours, what=f"{what} options_from needs {key!r}")
    return needs


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
    if scope == "interactive" or connect_path is not None:
        # Where a person is sent so the app can run the vendor's flow. Required
        # on an interactive connection, which has no other way to be filled at
        # all; offered on a static one, where it is the difference between an
        # admin typing an organization's name into a box and an admin running
        # the vendor's own install, on the vendor's page, for the whole guild.
        cleaned["connect_path"] = check_path(connect_path, what=f"{what} connect_path")

    if (
        scope == "static"
        and connect_path is not None
        and not any(field.get("managed") is True for field in fields)
    ):
        # The app writing back is the only way a static connection with a flow
        # is ever satisfied, so one with nothing managed to write into can do
        # nothing but leave the install unconfigured forever.
        fail(
            f"{what}: a static connection with a connect_path must declare a "
            "managed field for the flow to write into"
        )

    hint = _access_hint(connection.get("access_hint"), what=what)
    if hint is not None:
        cleaned["access_hint"] = hint
    return cleaned


# --- what an app offers -----------------------------------------------------


def _endpoint_identity(raw: Any, *, what: str) -> dict[str, Any] | None:
    """Which of an endpoint's returns identify the thing it touched.

    Shape only; that each part names a single-valued return of this endpoint is
    checked where the returns are known.
    """
    if raw is None:
        return None
    identity = require_mapping(raw, f"{what} identity")
    parts = require_list(
        identity.get("key"), f"{what} identity.key", MAX_IDENTITY_KEY_PARTS
    )
    if not parts:
        fail(f"{what} identity.key: name at least one return")
    return {
        "kind": check_identifier(identity.get("kind"), what=f"{what} identity.kind"),
        "key": [
            check_identifier(part, what=f"{what} identity.key entry") for part in parts
        ],
    }


def _check_identity_returns(
    identity: dict[str, Any], *, returns: list[dict[str, Any]], what: str
) -> None:
    """Every part of an address names a single value this endpoint hands back.

    Nothing downstream refuses a bad one — it simply resolves to nothing, and a
    fire somebody was waiting on is dropped without a word — so a part naming a
    return this endpoint does not declare, or one that is a list, is refused
    here. Half an address matches nothing, and one built from whichever parts
    happened to be present matches the wrong thing.
    """
    single = {value["key"] for value in returns if not value.get("list")}
    declared = {value["key"] for value in returns}
    for part in identity["key"]:
        if part not in declared:
            fail(f"{what} identity.key names {part!r}, which it does not return")
        if part not in single:
            fail(
                f"{what} identity.key names {part!r}, which is a list — "
                "an address is built from single values"
            )


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
            entry,
            types=PARAM_TYPES,
            allow_managed=False,
            what=f"{what} param",
            allow_list=True,
        )
        if param["key"] in seen:
            fail(f"{what}: two parameters share the key {param['key']!r}")
        seen.add(param["key"])
        params.append(param)

    cleaned: dict[str, Any] = {"id": endpoint_id, "direction": direction}

    # What this endpoint IS, in words, and what it hands back. Both belong to
    # every direction: an emission is the one thing here a person picks out of a
    # list without ever calling it, so it needs a name more than the others do,
    # and its payload is exactly as worth describing as a response.
    #
    # Stored and never read here. A label is somebody else's to render and a
    # return is somebody else's to bind, and this build assigns meaning to
    # neither — it bounds them, which is the whole of what a store owes a
    # document it passes on.
    label = localized_text(endpoint.get("label"), MAX_TEXT_LENGTH)
    if label is not None:
        cleaned["label"] = label
    description = localized_text(endpoint.get("description"), MAX_TEXT_LENGTH)
    if description is not None:
        cleaned["description"] = description
    returns = _returns(endpoint.get("returns"), what=what)
    if returns:
        cleaned["returns"] = returns

    # Where a consumer that groups an app's endpoints should file this one, and
    # what it needs to already have in hand. Both are opaque identifiers: the
    # vocabularies belong to whoever consumes them — the automation service
    # names the subjects a run can be about — and a second reading of a list
    # this build does not own would only ever drift from it.
    group = endpoint.get("group")
    if group is not None:
        cleaned["group"] = check_identifier(group, what=f"{what} group")
    needs = endpoint.get("needs_subject")
    if needs is not None:
        cleaned["needs_subject"] = check_identifier(needs, what=f"{what} needs_subject")

    # What this touched, or what it is about — the one thing here only the app
    # can know. A read has none: it touched nothing. Declaring the same kind and
    # key on a write and on the emission about it is what lets a consumer
    # recognise the change an automation made as its own, rather than firing
    # that automation again on it.
    identity = _endpoint_identity(endpoint.get("identity"), what=what)
    if identity is not None:
        if direction == "read":
            fail(f"{what}: a read endpoint has no identity — it touched nothing")
        _check_identity_returns(identity, returns=returns, what=what)
        cleaned["identity"] = identity

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


def _returns(raw: Any, *, what: str) -> list[dict[str, Any]]:
    """What an endpoint hands back, by name and type.

    Declared rather than discovered, because the consumer needs it before the
    endpoint has ever run: a widget binds a column and an automation offers a
    value for a later step to read, and both have to be refusable at the moment
    somebody arranges them rather than the first time one fires.

    ``list`` says several rather than one. It matters to a caller that has
    somewhere to put exactly one value — a form field, a tile's number — which
    is why it is a flag here rather than a second set of types.
    """
    if raw is None:
        return []
    declared = require_list(raw, f"{what} returns", MAX_RETURNS_PER_ENDPOINT)
    returns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in declared:
        value = require_mapping(entry, f"{what} return")
        key = check_identifier(value.get("key"), what=f"{what} return key")
        if key in seen:
            fail(f"{what}: two returns share the key {key!r}")
        seen.add(key)
        value_type = value.get("type")
        if value_type not in RETURN_TYPES:
            fail(f"{what} return {key!r}: unknown type {value_type!r}")
        cleaned: dict[str, Any] = {"key": key, "type": value_type}
        # Optional, unlike a param's: a param is a control somebody fills in and
        # needs a word on it, while a return is read by name and is often shown
        # under one the consumer supplies.
        label = localized_text(value.get("label"), MAX_TEXT_LENGTH)
        if label is not None:
            cleaned["label"] = label
        if value.get("list") is True:
            cleaned["list"] = True
        returns.append(cleaned)
    return returns


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


def _check_option_sources(
    endpoints: list[dict[str, Any]], *, readable_ids: set[str]
) -> None:
    """Every ``options_from`` against the endpoint it names.

    Three things have to hold, and each of them fails silently downstream:

    * the endpoint is one this manifest declares — an id from another app is a
      cross-app read with no consent story behind it;
    * it *reads*, because filling in a form must not write anything;
    * the keys it names are returns of that endpoint, and are lists. One value
      cannot be a menu, and a caller asking for options would get a scalar it
      has nowhere to put;
    * every ``needs`` entry joins a parameter that endpoint takes to one this
      endpoint declares — and never to this parameter itself, which would ask
      for the answer being filled in.
    """
    returns_by_id = {
        endpoint["id"]: {value["key"]: value for value in endpoint.get("returns") or []}
        for endpoint in endpoints
    }
    params_by_id = {
        endpoint["id"]: {param["key"] for param in endpoint.get("params") or []}
        for endpoint in endpoints
    }

    for endpoint in endpoints:
        for param in endpoint.get("params") or []:
            source = param.get("options_from")
            if not source:
                continue
            what = (
                f"service app: endpoint {endpoint['id']!r} parameter {param['key']!r}"
            )
            named = source["endpoint"]

            if named not in returns_by_id:
                fail(
                    f"{what}: options_from names {named!r}, which is not declared here"
                )
            if named not in readable_ids:
                fail(f"{what}: options_from names {named!r}, which does not read")

            for field in ("key", "label_key"):
                key = source.get(field)
                if key is None:
                    continue
                value = returns_by_id[named].get(key)
                if value is None:
                    fail(
                        f"{what}: options_from {field} {key!r} is not returned by {named!r}"
                    )
                if value.get("list") is not True:
                    fail(
                        f"{what}: options_from {field} {key!r} is a single value — "
                        "options come from a list"
                    )

            for theirs, ours in (source.get("needs") or {}).items():
                if theirs not in params_by_id.get(named, set()):
                    fail(
                        f"{what}: options_from needs {theirs!r}, "
                        f"which {named!r} does not take"
                    )
                if ours == param["key"]:
                    fail(
                        f"{what}: options_from needs {ours!r}, "
                        "which is the parameter being filled in"
                    )
                if ours not in params_by_id.get(endpoint["id"], set()):
                    fail(
                        f"{what}: options_from needs {ours!r}, "
                        "which this endpoint does not declare"
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

    # A parameter naming where its values come from, checked once every endpoint
    # is known. Nothing downstream refuses a bad one: a form asks this
    # deployment to resolve it, no such return is found, and the form offers
    # nothing — which is indistinguishable from a vendor being slow.
    _check_option_sources(endpoints, readable_ids=readable_ids)

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
