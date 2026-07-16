"""
Shared test utilities and factories.

Re-exports all factory functions for convenient imports:
    from app.testing import create_user, create_guild, get_auth_headers

Tenant factories are schema-native: they route the session to the target
guild's ``guild_<id>`` schema before touching the database (see
``schema_harness``). For raw tenant reads on a not-yet-routed session, use
``route_session_to_guild``.
"""

from app.testing.actor import Actor, make_actor
from app.testing.factories import (
    create_calendar_event,
    create_calendar_event_property_value,
    create_comment,
    create_counter,
    create_counter_group,
    create_document,
    create_document_property_value,
    create_federated_identity,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_property_definition,
    create_queue,
    create_queue_item,
    create_subtask,
    create_tag,
    create_task,
    create_task_property_value,
    create_task_status,
    create_upload,
    create_user,
    get_auth_headers,
    get_auth_token,
    get_new_access_token,
)
from app.testing.schema_harness import route_session_to_guild

__all__ = [
    "Actor",
    "make_actor",
    "create_calendar_event",
    "create_calendar_event_property_value",
    "create_comment",
    "create_counter",
    "create_counter_group",
    "create_document",
    "create_document_property_value",
    "create_federated_identity",
    "create_guild",
    "create_guild_membership",
    "create_initiative",
    "create_initiative_member",
    "create_project",
    "create_property_definition",
    "create_queue",
    "create_queue_item",
    "create_subtask",
    "create_tag",
    "create_task",
    "create_task_property_value",
    "create_task_status",
    "create_upload",
    "create_user",
    "get_auth_headers",
    "get_auth_token",
    "get_new_access_token",
    "route_session_to_guild",
]
