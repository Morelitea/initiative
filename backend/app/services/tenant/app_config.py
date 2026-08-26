"""Reading an install's connection schema, and holding what was typed into it.

An app declares *connections* — named groups of typed fields — and the pinned
definition is the only description of them this build trusts. A guild's answers
are validated against that pinned copy rather than against whatever the catalog
says today, so upgrading a listing can never retroactively change what an
existing install was allowed to store.

Two custody rules run through everything here:

* **A secret goes in and does not come back.** Values typed into a ``secret``
  field are encrypted per key and stored; a read reports only whether a value is
  present. Nothing in the API returns one, to anybody.
* **Managed keys are not typed at all.** A field the manifest marks ``managed``
  is written by the app itself when it completes a vendor flow, so this path
  refuses one rather than letting a form overwrite it.

Satisfaction is computed from presence alone — which fields have values. This
build never inspects a credential, calls a vendor, or learns a scope; whether a
credential carries the permissions it needs is the app's to report, and arrives
separately as ``config_state``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.core.encryption import SALT_APP_CONFIG, decrypt_field, encrypt_field
from app.core.messages import GuildAppMessages

__all__ = [
    "AppConfigError",
    "ConfigState",
    "MAX_CONFIG_VALUE_LENGTH",
    "MAX_SECRET_VALUE_LENGTH",
    "CONFIG_STATES",
    "apply_connection_values",
    "config_state",
    "connection_by_id",
    "decrypt_connection_secrets",
    "definition_connections",
    "has_value_map",
    "is_satisfied",
    "member_connection_ids",
    "needs_configuration",
    "prune_to_definition",
]

#: What a plain field may hold. Generous for a hostname or an account name,
#: small enough that the row stays configuration.
MAX_CONFIG_VALUE_LENGTH = 2_000
#: What a secret field may hold. Larger because a private-key PEM is a
#: legitimate credential for several vendors.
MAX_SECRET_VALUE_LENGTH = 16_000

#: What an app may report back about the configuration it was handed.
CONFIG_STATES: frozenset[str] = frozenset({"unverified", "ok", "invalid"})


class AppConfigError(Exception):
    """A configuration write this build will not store, as a message code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ConfigState:
    """What the UI needs to say whether an install still needs attention.

    ``needs_config`` is presence-derived and always knowable here.
    ``state`` / ``detail`` are the app's own verdict, which stays ``unverified``
    for an app that never reports — nothing blocks on the round trip.
    """

    needs_config: bool
    state: str
    detail: Optional[str] = None


# --- reading the pinned definition ------------------------------------------


def definition_connections(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The connections a pinned definition declares, in manifest order."""
    declared = (definition or {}).get("connections")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


def member_connection_ids(definition: dict[str, Any] | None) -> list[str]:
    """The ids of the connections each member holds their own credential for.

    ``interactive`` is the manifest's word for that half — one credential per
    person, obtained through the app's own vendor flow — as against ``static``,
    the single value a guild admin types for everybody.

    Read from the *declaration* rather than from the rows that happen to exist,
    so what an install is means the same thing before and after any particular
    member connects.
    """
    return [
        connection_id
        for connection in definition_connections(definition)
        if connection.get("scope") == "interactive"
        for connection_id in (connection.get("id"),)
        if isinstance(connection_id, str) and connection_id
    ]


def connection_by_id(
    definition: dict[str, Any] | None, connection_id: str
) -> Optional[dict[str, Any]]:
    for connection in definition_connections(definition):
        if connection.get("id") == connection_id:
            return connection
    return None


def _fields(connection: dict[str, Any]) -> list[dict[str, Any]]:
    declared = connection.get("fields")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


# --- validating what was typed ----------------------------------------------


def _coerce(field: dict[str, Any], value: Any) -> Any:
    """One submitted value, checked against its declared type.

    Types are the closed manifest enum, so this is a total match rather than a
    fallback: a field whose type this build does not know never reaches here,
    because the definition that declared it would not have validated.
    """
    field_type = field.get("type")

    if field_type == "bool":
        if not isinstance(value, bool):
            raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)
        return value

    if field_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)
        return value

    if not isinstance(value, str):
        raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)
    text = value.strip()
    if not text:
        raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)

    limit = (
        MAX_SECRET_VALUE_LENGTH if field_type == "secret" else MAX_CONFIG_VALUE_LENGTH
    )
    if len(text) > limit:
        raise AppConfigError(GuildAppMessages.CONFIG_VALUE_TOO_LONG)

    if field_type == "select":
        options = field.get("options")
        if not isinstance(options, list) or text not in options:
            raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)
        return text

    if field_type == "url":
        if not (text.startswith("https://") or text.startswith("http://")):
            raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)
        if " " in text:
            raise AppConfigError(GuildAppMessages.CONFIG_INVALID_VALUE)
        return text

    return text


def apply_connection_values(
    connection: dict[str, Any],
    submitted: dict[str, Any],
    *,
    current: dict[str, Any],
    current_secrets: dict[str, Any],
    allow_managed: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge a submitted form into one connection's stored values.

    Returns the new ``(config, secrets)`` for this connection. A key present
    with ``None`` is a clear; a key absent is left alone, so a form that renders
    a subset of the fields cannot wipe the rest. Secret values are encrypted on
    the way in and only ever leave again through
    :func:`decrypt_connection_secrets`.

    ``allow_managed`` is for the app's own write-back path, which is the only
    caller entitled to set a field the manifest marked ``managed``.
    """
    fields = {field["key"]: field for field in _fields(connection) if "key" in field}

    config = dict(current or {})
    secrets = dict(current_secrets or {})

    cleared: set[str] = set()
    for key, value in submitted.items():
        field = fields.get(key)
        if field is None:
            raise AppConfigError(GuildAppMessages.CONFIG_UNKNOWN_FIELD)
        if field.get("managed") is True and not allow_managed:
            raise AppConfigError(GuildAppMessages.CONFIG_MANAGED_FIELD)

        is_secret = field.get("type") == "secret"
        if value is None:
            config.pop(key, None)
            secrets.pop(key, None)
            cleared.add(key)
            continue

        coerced = _coerce(field, value)
        if is_secret:
            secrets[key] = encrypt_field(coerced, SALT_APP_CONFIG)
            config.pop(key, None)
        else:
            config[key] = coerced
            secrets.pop(key, None)

    # A required field left empty is a connection that cannot work, and saying
    # so at the point of the write is the difference between a form the admin
    # can fix and a widget that mysteriously stays dark.
    #
    # Clearing one is the exception, and deliberately so: taking a credential
    # back has to work at any moment, whether or not what remains adds up to a
    # working connection. What is left then reads as unconfigured — satisfaction
    # is recomputed from what is stored, so the capability lapses with it.
    for key, field in fields.items():
        if field.get("required") is not True or key in cleared:
            continue
        if key not in config and key not in secrets:
            raise AppConfigError(GuildAppMessages.CONFIG_REQUIRED_FIELD)

    return config, secrets


def decrypt_connection_secrets(secrets: dict[str, Any] | None) -> dict[str, str]:
    """The plaintext values, for the one caller that hands them to the app.

    Never reached from a response path: the API's own reads report presence.
    """
    out: dict[str, str] = {}
    for key, ciphertext in (secrets or {}).items():
        if isinstance(ciphertext, str):
            out[key] = decrypt_field(ciphertext, SALT_APP_CONFIG)
    return out


# --- presence, and what it implies ------------------------------------------


def prune_to_definition(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    """Stored values, minus anything the definition no longer declares.

    Used when an install moves to a new version. A value cannot outlive the
    field it was typed into, and the pruning has to reach fields rather than
    stopping at connections: a version that keeps a connection but drops one of
    its fields would otherwise leave that value stored, and a non-secret one
    would keep appearing in the install's own detail payload.

    Returns the pruned maps and the ids of connections the definition dropped
    entirely, which the caller revokes — the app is still holding whatever
    those values bought it.
    """
    declared: dict[str, set[str]] = {
        connection["id"]: {
            field["key"] for field in _fields(connection) if "key" in field
        }
        for connection in definition_connections(definition)
        if isinstance(connection.get("id"), str)
    }

    def _prune(stored: dict[str, Any] | None) -> dict[str, Any]:
        kept: dict[str, Any] = {}
        for connection_id, values in (stored or {}).items():
            fields = declared.get(connection_id)
            if fields is None or not isinstance(values, dict):
                continue
            surviving = {key: value for key, value in values.items() if key in fields}
            # An emptied connection is stored as absent rather than as an empty
            # map, so "has anything been configured here?" has one shape.
            if surviving:
                kept[connection_id] = surviving
        return kept

    dropped = {
        connection_id
        for connection_id in {*(config or {}), *(secrets or {})}
        if connection_id not in declared
    }
    return _prune(config), _prune(secrets), dropped


def has_value_map(
    connection: dict[str, Any],
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> dict[str, bool]:
    """Which of a connection's fields hold a value.

    This is the whole of what a client is told about a stored credential, and
    the only input to satisfaction.
    """
    stored_config = config or {}
    stored_secrets = secrets or {}
    return {
        field["key"]: (field["key"] in stored_config or field["key"] in stored_secrets)
        for field in _fields(connection)
        if "key" in field
    }


def is_satisfied(
    connection: dict[str, Any],
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> bool:
    """Whether this connection has everything it declared it needs.

    A connection with no required fields is satisfied once anything is set,
    which is what "connected" means for a flow whose result is one managed
    token. A connection with no fields at all is never satisfied by presence —
    only an interactive one can be, and it becomes so when the app writes back.
    """
    present = has_value_map(connection, config, secrets)
    if not present:
        return False
    required = [
        field["key"]
        for field in _fields(connection)
        if field.get("required") is True and "key" in field
    ]
    if required:
        return all(present.get(key, False) for key in required)
    return any(present.values())


def needs_configuration(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> bool:
    """Whether a guild admin still has something to fill in.

    Only guild-scoped (``static``) connections count. A per-member connection
    nobody has completed is not an unfinished install — installation is never
    gated on one, and members connect when and if they want what it unlocks.
    """
    stored_config = config or {}
    stored_secrets = secrets or {}
    for connection in definition_connections(definition):
        if connection.get("scope") != "static":
            continue
        connection_id = connection.get("id")
        if not isinstance(connection_id, str):
            continue
        if not is_satisfied(
            connection,
            stored_config.get(connection_id) or {},
            stored_secrets.get(connection_id) or {},
        ):
            return True
    return False


def config_state(app: Any) -> ConfigState:
    """The combined answer the settings page shows for an install."""
    return ConfigState(
        needs_config=needs_configuration(
            app.definition, app.config, app.config_secrets
        ),
        state=app.config_state if app.config_state in CONFIG_STATES else "unverified",
        detail=app.config_state_detail,
    )
