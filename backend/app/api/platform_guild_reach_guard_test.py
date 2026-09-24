"""Static guard: where the platform surface routes into a community's schema.

The platform's routes and services (``app/api/v1/platform_endpoints/`` and
``app/services/platform/``) reach guild content only at the call sites named in
``_ALLOWED`` below. A platform actor who needs to read or change what is inside
a community holds a grant and goes through the seam on that community's own
routes; what is listed here is lifecycle work, aggregates, and the routes that
are already the seam or act on the caller's own community.

A call site is a call, in one of those two trees, to something that routes a
session into ``guild_<id>`` and is given a community to route into:

* the primitives — ``set_rls_context`` with a ``guild_id``,
  ``set_system_guild_context``, ``guild_schema_context``,
  ``establish_guild_access``, and the test helpers ``route_as`` /
  ``route_system``;
* a *wrapper* — a function in those trees, other than a route handler, that
  passes one of its own parameters as the community to any of the above (or to
  another wrapper). Its callers are the call sites, since they pick the
  community. The wrappers are pinned in ``_WRAPPERS`` so a new one is a
  decision too.

``set_billing_context`` is not a routing into ``guild_<id>``: it assumes the
billing service's own role, which reads billing rows only.

Each entry is keyed by (module, enclosing function) and carries the reason it
is there. A call site missing from the list fails; an entry with no call site
left fails too, so the list stays a statement of what is true.

The walk is syntactic, in the style of ``context_seam_guard_test``: it matches
calls as written and does not follow a callable through a variable.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_APP_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _APP_DIR.parent

_SCANNED = ("api/v1/platform_endpoints", "services/platform")

#: Callee name → (keyword naming the community, its position when passed
#: positionally, or None where it is keyword-only).
_PRIMITIVES: dict[str, tuple[str, int | None]] = {
    "set_rls_context": ("guild_id", 2),
    "set_system_guild_context": ("guild_id", None),
    "guild_schema_context": ("guild_id", None),
    "establish_guild_access": ("guild_id", 2),
    "route_as": ("guild_id", None),
    "route_system": ("guild_id", None),
}

_ROUTE_DECORATORS = frozenset(
    {"get", "post", "put", "patch", "delete", "websocket", "api_route"}
)

_ENDPOINTS = "app/api/v1/platform_endpoints"
_SERVICES = "app/services/platform"

#: Functions that route into whichever community their caller names.
_WRAPPERS: dict[tuple[str, str], str] = {
    (f"{_SERVICES}/billing.py", "guild_storage_usage"): (
        "storage aggregate for the billing service"
    ),
    (f"{_SERVICES}/guilds.py", "align_admin_initiative_roles"): (
        "reconciles a promoted admin's initiative rows, on the system engine "
        "beside the membership role write (the guild role holds no UPDATE on "
        "guild_memberships)"
    ),
    (f"{_SERVICES}/guilds.py", "enroll_new_member_in_auto_join_initiatives"): (
        "enrolls a new member in the community's auto-join initiatives"
    ),
    (f"{_SERVICES}/guilds.py", "ensure_membership"): (
        "adds a membership and its auto-join enrolments"
    ),
    (f"{_SERVICES}/guilds.py", "join_community_guild"): (
        "the caller joins a listed community"
    ),
    (f"{_SERVICES}/guilds.py", "restore_guild"): (
        "brings a deleted community back and seats its superadmin, with the "
        "seat's auto-join enrolments (ensure_membership)"
    ),
    (f"{_SERVICES}/guilds.py", "seed_guild_content"): (
        "provisions and seeds a new community's schema"
    ),
    (f"{_SERVICES}/guild_purge.py", "_delete_expired_hold"): (
        "deletes one community whose hold ran out, letting go of its app "
        "connections in its own schema"
    ),
    (f"{_SERVICES}/intake_setup.py", "_route"): (
        "intake setup's routing helper: the platform owner's Intake page, into the operations community"
    ),
    (f"{_SERVICES}/provider_placement.py", "_initiatives_in"): (
        "reads one community's initiatives and roles for a provider placement rule"
    ),
    (f"{_SERVICES}/provider_placement.py", "_resolve_destination"): (
        "checks a provider placement rule's initiative is the named community's"
    ),
    (f"{_SERVICES}/provider_placement.py", "list_targets"): (
        "lists a placeable community's initiatives for a provider placement rule"
    ),
}

#: Every call site that routes into a community, and why it may.
_ALLOWED: dict[tuple[str, str], str] = {
    # --- The seam itself ---------------------------------------------------
    (f"{_ENDPOINTS}/delegation_exchange.py", "exchange_delegation"): (
        "routes the delegated member through establish_guild_access"
    ),
    (f"{_ENDPOINTS}/guilds.py", "leave_guild"): (
        "routes the leaving member through establish_guild_access"
    ),
    # --- The caller's own community, behind its settings gate -------------
    (f"{_ENDPOINTS}/guilds.py", "update_guild_membership"): (
        "the caller's own community's role route, as its settings admin: the "
        "role write and the initiative reconcile after it run on the system "
        "engine (the guild role holds no UPDATE on guild_memberships)"
    ),
    # --- Joining and creating ----------------------------------------------
    (f"{_ENDPOINTS}/auth.py", "_register_account"): (
        "a new account joins the community it was invited to, or creates one"
    ),
    (f"{_ENDPOINTS}/guilds.py", "create_guild"): ("seeds a community just created"),
    (f"{_ENDPOINTS}/guilds.py", "join_community_guild"): (
        "the caller joins a listed community"
    ),
    (f"{_SERVICES}/guilds.py", "create_guild"): (
        "the creator's membership in a community just created"
    ),
    (f"{_SERVICES}/guilds.py", "redeem_invite_for_user"): (
        "the invitee joins the community the invite names"
    ),
    # --- Lifecycle -----------------------------------------------------------
    (f"{_ENDPOINTS}/settings.py", "restore_platform_guild"): (
        "restores a deleted community and seats its superadmin (guilds.manage)"
    ),
    (f"{_SERVICES}/app_settings.py", "ensure_defaults"): (
        "startup seeding of the primary community"
    ),
    (f"{_SERVICES}/guild_purge.py", "delete_expired_holds"): (
        "the scheduled sweep that deletes communities whose hold ran out"
    ),
    # --- Aggregates ----------------------------------------------------------
    (f"{_ENDPOINTS}/billing.py", "guild_usage"): (
        "storage usage for the billing service"
    ),
    # --- Account closure and erasure -----------------------------------------
    (f"{_SERVICES}/users.py", "_drop_user_memberships"): (
        "account closure: the account's own communities"
    ),
    (f"{_SERVICES}/users.py", "_end_app_access_everywhere"): (
        "account closure: the account's own communities"
    ),
    (f"{_SERVICES}/users.py", "soft_delete_user"): (
        "account erasure: every community the account's content may be in"
    ),
    (f"{_SERVICES}/users.py", "hard_delete_user"): (
        "account erasure: every community the account's content may be in"
    ),
    # --- Intake: the platform owner's setting, in the operations community ---
    (f"{_SERVICES}/intake.py", "stream_is_bound"): (
        "intake: opens a case in the operations community on the deployment's behalf"
    ),
    (f"{_SERVICES}/intake.py", "open_case"): (
        "intake: opens a case in the operations community on the deployment's behalf"
    ),
    (f"{_SERVICES}/intake_setup.py", "bind"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "unbind"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "list_bindings"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "list_options"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    (f"{_SERVICES}/intake_setup.py", "provision_from_blueprint"): (
        "intake setup: the platform owner's Intake page (config.manage)"
    ),
    # --- Provider placement rules: one placeable community at a time ------
    (f"{_ENDPOINTS}/provider_placement.py", "list_placement_targets"): (
        "the initiatives a provider placement rule may name, in a community "
        "its rules apply to"
    ),
    (f"{_SERVICES}/provider_placement.py", "list_rules"): (
        "names the initiatives provider placement rules place into, in the "
        "communities they apply to"
    ),
    (f"{_SERVICES}/provider_placement.py", "_read_one"): (
        "names the initiative a provider placement rule places into"
    ),
    (f"{_SERVICES}/provider_placement.py", "create_rule"): (
        "checks a new provider placement rule's initiative"
    ),
    (f"{_SERVICES}/provider_placement.py", "update_rule"): (
        "checks a changed provider placement rule's initiative"
    ),
}


@dataclass(frozen=True)
class _Function:
    module: str
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef

    @property
    def key(self) -> tuple[str, str]:
        return (self.module, self.qualname)


def _scanned_files() -> list[Path]:
    return [
        path
        for root in _SCANNED
        for path in sorted((_APP_DIR / root).rglob("*.py"))
        if not path.name.endswith("_test.py")
    ]


def _functions(path: Path) -> list[_Function]:
    module = path.relative_to(_BACKEND_DIR).as_posix()
    found: list[_Function] = []

    def visit(node: ast.AST, prefix: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = (*prefix, child.name)
                found.append(_Function(module, ".".join(name), child))
                visit(child, name)
            elif isinstance(child, ast.ClassDef):
                visit(child, (*prefix, child.name))
            else:
                visit(child, prefix)

    visit(ast.parse(path.read_text()), ())
    return found


def _callee(node: ast.Call) -> str | None:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _own_calls(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    """Calls in the function's own body, not in functions nested inside it."""
    calls: list[ast.Call] = []
    pending: list[ast.AST] = list(fn.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            calls.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return calls


def _community_argument(
    call: ast.Call, keyword: str, position: int | None
) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == keyword:
            if isinstance(kw.value, ast.Constant) and kw.value.value is None:
                return None
            return kw.value
    if position is not None and len(call.args) > position:
        return call.args[position]
    return None


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr in _ROUTE_DECORATORS
        for d in fn.decorator_list
    )


def _parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = fn.args
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


def _walk() -> tuple[dict[tuple[str, str], list[int]], set[tuple[str, str]]]:
    """(call sites → line numbers, wrappers found)."""
    functions = [fn for path in _scanned_files() for fn in _functions(path)]

    routers = dict(_PRIMITIVES)
    wrappers: dict[str, tuple[str, str]] = {}
    grew = True
    while grew:
        grew = False
        for fn in functions:
            if _is_route(fn.node) or fn.node.name in routers:
                continue
            params = _parameters(fn.node)
            for call in _own_calls(fn.node):
                name = _callee(call)
                if name not in routers:
                    continue
                arg = _community_argument(call, *routers[name])
                if isinstance(arg, ast.Name) and arg.id in params:
                    positional = [
                        a.arg for a in (*fn.node.args.posonlyargs, *fn.node.args.args)
                    ]
                    routers[fn.node.name] = (
                        arg.id,
                        positional.index(arg.id) if arg.id in positional else None,
                    )
                    wrappers[fn.node.name] = fn.key
                    grew = True
                    break

    wrapper_keys = set(wrappers.values())
    sites: dict[tuple[str, str], list[int]] = {}
    for fn in functions:
        if fn.key in wrapper_keys:
            continue
        for call in _own_calls(fn.node):
            name = _callee(call)
            if name not in routers:
                continue
            if _community_argument(call, *routers[name]) is None:
                continue
            sites.setdefault(fn.key, []).append(call.lineno)
    return sites, wrapper_keys


def test_platform_routes_into_a_community_only_where_listed():
    sites, _ = _walk()
    unlisted = sorted(
        f"{module}:{min(lines)} in {function}"
        for (module, function), lines in sites.items()
        if (module, function) not in _ALLOWED
    )
    assert unlisted == [], (
        "the platform surface routes into a community here, and the list of "
        "places it may does not name it. Reach guild content from a "
        "/g/{guild_id} route through the seam instead, or add the site to "
        "_ALLOWED with the reason it belongs to the platform: " + ", ".join(unlisted)
    )


def test_every_listed_site_still_routes():
    sites, _ = _walk()
    stale = sorted(f"{m} {f}" for (m, f) in _ALLOWED if (m, f) not in sites)
    assert stale == [], (
        "these entries name a function that no longer routes into a "
        "community; remove them: " + ", ".join(stale)
    )


def test_the_wrappers_are_the_listed_ones():
    _, wrappers = _walk()
    unlisted = sorted(f"{m} {f}" for (m, f) in wrappers - set(_WRAPPERS))
    stale = sorted(f"{m} {f}" for (m, f) in set(_WRAPPERS) - wrappers)
    assert unlisted == [], (
        "these functions route into whichever community their caller names; "
        "list them in _WRAPPERS with what they are for: " + ", ".join(unlisted)
    )
    assert stale == [], (
        "these _WRAPPERS entries no longer route into a caller-named "
        "community; remove them: " + ", ".join(stale)
    )
