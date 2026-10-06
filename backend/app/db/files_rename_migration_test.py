"""Migrations 20261006_0462 and 20261006_0463 call the documents tool files.

Loaded by path and run on a guild the test builds: down to the names an older
release wrote, rows written that way, then up, down and up again, the way
``stored_values_migration_test`` runs its revisions.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.search import SearchEntityType
from app.models.platform.notification import NotificationType
from app.services.platform import notice_outbox, user_notifications
from app.testing import (
    create_dashboard,
    create_export_job,
    create_file,
    create_guild,
    create_guild_plugin,
    create_initiative,
    create_plugin_service_registration,
    create_project,
    create_property_definition,
    create_property_value,
    create_relationship,
    create_user,
)

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    path = _VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


_OLD_STATEMENT = "SELECT f.name, f.document_type FROM documents f"
_NEW_STATEMENT = "SELECT f.name, f.file_type FROM files f"


async def _guild_values(session, schema: str, ids: dict[str, int]) -> dict:
    s = f'"{schema}"'
    return {
        "grants": await _rows(
            session,
            f"SELECT DISTINCT resource_type FROM {s}.resource_grants "
            "WHERE resource_id = :id AND resource_type IN ('file', 'document')",
            id=ids["file"],
        ),
        "property": await _rows(
            session, f"SELECT entity_type FROM {s}.property_values"
        ),
        "edge": await _rows(
            session,
            f"SELECT source_type, target_type, source_node, target_node "
            f"FROM {s}.relationships",
        ),
        "search": await _rows(
            session,
            f"SELECT DISTINCT entity_type, dac_tool FROM {s}.search_entries "
            "WHERE entity_id = :id AND entity_type IN ('file', 'document')",
            id=ids["file"],
        ),
        "permissions": await _rows(
            session,
            f"SELECT DISTINCT permission_key FROM {s}.initiative_role_permissions "
            "WHERE permission_key ~ '(file|document)' ORDER BY 1",
        ),
        "outbox": await _rows(
            session,
            f"SELECT resource_type, parents, changed FROM {s}.event_outbox "
            "WHERE id = :id",
            id=ids["outbox"],
        ),
        "webhook": await _rows(
            session, f"SELECT event_types, fields FROM {s}.webhook_subscriptions"
        ),
        "plugin": await _rows(
            session, f"SELECT granted_scopes, definition FROM {s}.guild_plugins"
        ),
        "dashboard": await _rows(
            session,
            f"SELECT definition FROM {s}.dashboards WHERE id = :id",
            id=ids["dashboard"],
        ),
        "export": await _rows(
            session,
            f"SELECT source, params FROM {s}.export_jobs WHERE id = :id",
            id=ids["export"],
        ),
    }


async def test_guild_values_say_file_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    schema = f"guild_{guild.id}"
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    file = await create_file(session, initiative, user)
    definition = await create_property_definition(session, initiative)
    await create_property_value(session, file, definition, value_text="kept")
    await create_relationship(
        session,
        guild,
        source=(SearchEntityType.project, project.id),
        target=(SearchEntityType.file, file.id),
    )
    plugin_definition = {"service": {"scopes": ["documents:read", "tasks:read"]}}
    await create_guild_plugin(
        session,
        guild,
        user,
        definition=plugin_definition,
        granted_scopes=["documents:read", "documents:write"],
    )
    sheet = {"source": "sheet_range", "document_id": file.id, "range": "A1:B2"}
    dashboard = await create_dashboard(
        session,
        initiative,
        user,
        definition={
            "widgets": [
                {"binding": {"source": "query", "sql": _OLD_STATEMENT}},
                {"binding": sheet},
                {"binding": {"entity": "document"}},
            ]
        },
    )
    job = await create_export_job(
        session,
        guild,
        user,
        source="document",
        params={"document_ids": [file.id], "formats": {"document": "pdf"}},
    )
    await session.commit()

    files = _load("20261006_0462_documents_are_files.py")

    def run(forward: bool):
        def apply(sync_session) -> None:
            bind = sync_session.connection()
            codes = files._KIND_CODES_AFTER if forward else files._KIND_CODES_BEFORE
            bind.exec_driver_sql(files._kind_code_fn(codes))
            bind.execute(
                text("SELECT set_config('search_path', :sp, true)"),
                {"sp": f"{schema}, public"},
            )
            with Operations.context(MigrationContext.configure(bind)):
                files._apply(forward)

        return apply

    try:
        await session.run_sync(run(False))
        outbox_id = (
            await _rows(
                session,
                f'INSERT INTO "{schema}".event_outbox (txn_id, occurred_at, '
                "resource_type, resource_id, action, parents, changed) VALUES "
                "(1, now(), 'documents', :id, 'updated', "
                "CAST(:parents AS jsonb), ARRAY['document_type', 'name']) "
                "RETURNING id",
                id=file.id,
                parents=json.dumps([{"id": file.id, "type": "documents"}]),
            )
        )[0][0]
        await (await session.connection()).execute(
            text(
                f'INSERT INTO "{schema}".webhook_subscriptions (target_url, '
                "hmac_secret, event_types, fields) VALUES ('https://hook.test', "
                "'s', ARRAY['documents.updated', 'tasks.created'], "
                "ARRAY['document_type', 'name'])"
            )
        )
        await session.commit()
        ids = {
            "file": file.id,
            "outbox": outbox_id,
            "dashboard": dashboard.id,
            "export": job.id,
        }
        old = await _guild_values(session, schema, ids)

        await session.run_sync(run(True))
        await session.commit()
        node = (6 << 32) | file.id
        new = await _guild_values(session, schema, ids)
        assert new["grants"] == [("file",)]
        assert new["property"] == [("file",)]
        ((source, target, *nodes),) = new["edge"]
        assert {source, target} == {"project", "file"} and node in nodes
        # The node ids are computed, and the file kind keeps its code.
        assert [edge[2:] for edge in new["edge"]] == [edge[2:] for edge in old["edge"]]
        assert new["search"] == [("file", "file")]
        assert new["permissions"] == [("create_files",), ("files_enabled",)]
        assert new["outbox"] == [
            ("files", [{"id": file.id, "type": "files"}], ["file_type", "name"])
        ]
        assert new["webhook"] == [
            (["files.updated", "tasks.created"], ["file_type", "name"])
        ]
        assert new["plugin"] == [
            (
                ["files:read", "files:write"],
                {"service": {"scopes": ["files:read", "tasks:read"]}},
            )
        ]
        assert new["dashboard"] == [
            (
                {
                    "widgets": [
                        {"binding": {"source": "query", "sql": _NEW_STATEMENT}},
                        {
                            "binding": {
                                "source": "sheet_range",
                                "file_id": file.id,
                                "range": "A1:B2",
                            }
                        },
                        {"binding": {"entity": "file"}},
                    ]
                },
            )
        ]
        assert new["export"] == [
            ("file", {"file_ids": [file.id], "formats": {"file": "pdf"}})
        ]

        await session.run_sync(run(False))
        await session.commit()
        assert await _guild_values(session, schema, ids) == old
        assert old["grants"] == [("document",)]
    finally:
        await session.run_sync(run(True))
        await session.commit()


async def _public_values(session, user_id: int, registration_id: int) -> dict:
    return {
        "lines": await _rows(
            session,
            "SELECT tool, subject_type, CAST(data AS jsonb) FROM public.notifications "
            "WHERE user_id = :u ORDER BY id",
            u=user_id,
        ),
        "queued": await _rows(
            session,
            "SELECT data, push_data, rollup_key, email_link FROM public.notice_outbox "
            "WHERE user_id = :u",
            u=user_id,
        ),
        "ceiling": await _rows(
            session,
            "SELECT scope_ceiling FROM public.plugin_service_registrations "
            "WHERE id = :id",
            id=registration_id,
        ),
    }


async def test_public_values_say_file_and_back(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    line = {
        "tool": "document",
        "subject_type": "document",
        "entity_type": "document",
        "entity_id": 5,
        "target_path": "/go/document/5",
        "smart_link": "https://app.test/navigate?community_id=1&target=%2Fgo%2Fdocument%2F5",
        "rollup_key": "document-body:5",
    }
    page = {"target_path": "/c/1/i/2/documents/5", "rollup_key": "document:5"}
    for data in (line, page):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.mention,
            data=data,
        )
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                user.id,
                guild.id,
                NotificationType.mention,
                {"context_entity_type": "document", "target_path": "/go/document/5"},
                push_data={"target_path": "/go/document/5"},
            )
        ],
    )
    registration = await create_plugin_service_registration(
        session, scope_ceiling=["documents:read", "tasks:read"]
    )
    await (await session.connection()).execute(
        text(
            "UPDATE public.notifications SET tool = 'document', "
            "subject_type = 'document' WHERE user_id = :u"
        ),
        {"u": user.id},
    )
    await (await session.connection()).execute(
        text(
            "UPDATE public.notice_outbox SET rollup_key = 'document-body:5', "
            "email_link = 'https://app.test/navigate?target=%2Fgo%2Fdocument%2F5' "
            "WHERE user_id = :u"
        ),
        {"u": user.id},
    )
    for key in ("documents:view-mode", "my-tasks"):
        await (await session.connection()).execute(
            text(
                "INSERT INTO public.user_view_preferences "
                "(user_id, scope_key, value, updated_at) "
                "VALUES (:u, :k, CAST('{}' AS json), now())"
            ),
            {"u": user.id, "k": key},
        )
    await session.commit()
    migration = _load("20261006_0463_documents_are_files_in_public.py")
    old = await _public_values(session, user.id, registration.id)

    def run(step):
        def apply(sync_session) -> None:
            with Operations.context(
                MigrationContext.configure(sync_session.connection())
            ):
                step()

        return apply

    await session.run_sync(run(migration.upgrade))
    await session.commit()
    try:
        assert await _public_values(session, user.id, registration.id) == {
            "lines": [
                (
                    "file",
                    "file",
                    {
                        **line,
                        "tool": "file",
                        "subject_type": "file",
                        "entity_type": "file",
                        "target_path": "/go/file/5",
                        "smart_link": "https://app.test/navigate?community_id=1"
                        "&target=%2Fgo%2Ffile%2F5",
                        "rollup_key": "file-body:5",
                    },
                ),
                (
                    "file",
                    "file",
                    {"target_path": "/c/1/i/2/files/5", "rollup_key": "file:5"},
                ),
            ],
            "queued": [
                (
                    {"context_entity_type": "file", "target_path": "/go/file/5"},
                    {"target_path": "/go/file/5"},
                    "file-body:5",
                    "https://app.test/navigate?target=%2Fgo%2Ffile%2F5",
                )
            ],
            "ceiling": [(["files:read", "tasks:read"],)],
        }
        kept = await _rows(
            session,
            "SELECT scope_key FROM public.user_view_preferences WHERE user_id = :u",
            u=user.id,
        )
        assert kept == [("my-tasks",)]
        assert await _rows(session, "SELECT to_regtype('public.file_type')") != [
            (None,)
        ]
    finally:
        await session.run_sync(run(migration.downgrade))
        await session.commit()
    assert await _public_values(session, user.id, registration.id) == old
    await session.run_sync(run(migration.upgrade))
    await session.commit()
