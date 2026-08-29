"""The audit board: who may read it, and what it says."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.user import UserRole
from app.services import audit as audit_service
from app.testing import create_user
from app.testing.factories import get_auth_headers

pytestmark = pytest.mark.integration

BOARD = "/api/v1/admin/audit-events"


async def _record(session, actor, subject):
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
        target_user_id=subject.id,
        target_type="user",
        target_id=subject.id,
    )
    await session.commit()


class TestWhoMayRead:
    @pytest.mark.parametrize(
        "role", [UserRole.support, UserRole.moderator, UserRole.owner]
    )
    async def test_audit_read_holders(
        self, client: AsyncClient, session: AsyncSession, role
    ):
        reader = await create_user(session, role=role)

        response = await client.get(BOARD, headers=get_auth_headers(reader))

        assert response.status_code == 200, response.text

    async def test_a_member_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        member = await create_user(session, role=UserRole.member)

        response = await client.get(BOARD, headers=get_auth_headers(member))

        assert response.status_code == 403


class TestWhatItSays:
    async def test_an_entry_names_both_sides_by_handle(
        self, client: AsyncClient, session: AsyncSession
    ):
        actor = await create_user(session, role=UserRole.moderator, username="modsy")
        subject = await create_user(session, username="subject")
        await _record(session, actor, subject)

        response = await client.get(
            BOARD,
            headers=get_auth_headers(actor),
            params={"actor_user_id": actor.id},
        )

        entry = response.json()["items"][0]
        assert entry["event_type"] == "user.avatar_removed"
        assert entry["actor"]["username"] == "modsy"
        assert entry["target_user"]["username"] == "subject"
        assert entry["target_type"] == "user"

    async def test_an_entry_outlives_the_account_it_names(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The row holds ids, so an erased subject resolves to nothing and the
        record of what was done to them stays readable."""
        actor = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)
        subject_id = subject.id
        await _record(session, actor, subject)

        await session.delete(subject)
        await session.commit()

        response = await client.get(
            BOARD, headers=get_auth_headers(actor), params={"actor_user_id": actor.id}
        )

        entry = response.json()["items"][0]
        assert entry["target_user"] == {
            "id": subject_id,
            "username": None,
            "discriminator": None,
        }

    async def test_filtering_by_subject(
        self, client: AsyncClient, session: AsyncSession
    ):
        actor = await create_user(session, role=UserRole.moderator)
        wanted = await create_user(session)
        other = await create_user(session)
        await _record(session, actor, wanted)
        await _record(session, actor, other)

        response = await client.get(
            BOARD, headers=get_auth_headers(actor), params={"target_user_id": wanted.id}
        )

        body = response.json()
        assert body["total_count"] == 1
        assert body["items"][0]["target_user"]["id"] == wanted.id


class TestTheTakedownRecordsItself:
    async def test_removing_a_picture_writes_an_entry(
        self, client: AsyncClient, session: AsyncSession
    ):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session, avatar_url="https://idp.example/pic.png")

        removal = await client.delete(
            f"/api/v1/admin/users/{subject.id}/avatar",
            headers=get_auth_headers(moderator),
        )
        assert removal.status_code == 204, removal.text

        board = await client.get(
            BOARD,
            headers=get_auth_headers(moderator),
            params={"target_user_id": subject.id},
        )

        entry = board.json()["items"][0]
        assert entry["event_type"] == "user.avatar_removed"
        assert entry["actor"]["id"] == moderator.id
