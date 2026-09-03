"""The three rules the transport adds, exercised through the SQL itself.

Same shape as ``dm_rules_test``: the functions *are* the rule, so a test that
agreed with a Python restatement of them would prove nothing about what the
request path gets.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.contact_grant import (
    ContactGrant,
    ContactGrantKind,
    ContactGrantState,
    canonical_pair,
)
from app.models.platform.dm_conversation import (
    DmConversation,
    DmConversationMember,
)
from app.models.platform.dm_device import DmDevice
from app.models.platform.dm_one_time_key import DmOneTimeKey
from app.models.platform.user import User
from app.models.platform.user_dm_settings import DmPolicy, UserDmSettings
from app.models.platform.user_ignore import UserIgnore
from app.testing import create_user

pytestmark = pytest.mark.asyncio


async def _policy(session: AsyncSession, user: User, policy: DmPolicy) -> None:
    row = await session.get(UserDmSettings, user.id)
    if row is None:
        row = UserDmSettings(user_id=user.id)
        session.add(row)
    row.dm_policy = policy
    await session.flush()


async def _open_channel(session: AsyncSession, a: User, b: User) -> None:
    """The accepted message grant that makes a pair reachable."""
    low, high = canonical_pair(a.id, b.id)
    session.add(
        ContactGrant(
            user_id_low=low,
            user_id_high=high,
            kind=ContactGrantKind.message,
            state=ContactGrantState.accepted,
            requested_by=a.id,
        )
    )
    await session.flush()


async def _as(session: AsyncSession, user: User) -> None:
    await session.exec(
        text("SELECT set_config('app.current_user_id', :v, true)").bindparams(
            v=str(user.id)
        )
    )


async def _device(session: AsyncSession, user: User) -> DmDevice:
    device = DmDevice(
        user_id=user.id,
        identity_key=b"identity-" + str(user.id).encode(),
        fingerprint_key=b"fingerprint-" + str(user.id).encode(),
    )
    session.add(device)
    await session.flush()
    return device


async def _conversation(session: AsyncSession, *users: User) -> DmConversation:
    conversation = DmConversation()
    session.add(conversation)
    await session.flush()
    for user in users:
        session.add(
            DmConversationMember(conversation_id=conversation.id, user_id=user.id)
        )
    await session.flush()
    return conversation


async def _in_conversation(
    session: AsyncSession, user: User, conversation: DmConversation
) -> bool:
    await _as(session, user)
    return (
        await session.exec(
            text("SELECT public.dm_in_conversation(:c)").bindparams(c=conversation.id)
        )
    ).scalar_one()


async def _deliverable(session: AsyncSession, actor: User, target: User) -> bool:
    await _as(session, actor)
    return (
        await session.exec(
            text("SELECT public.dm_deliverable(:t)").bindparams(t=target.id)
        )
    ).scalar_one()


class TestInConversation:
    async def test_member_is_in_it(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        conversation = await _conversation(session, alice, bob)

        assert await _in_conversation(session, alice, conversation) is True
        assert await _in_conversation(session, bob, conversation) is True

    async def test_everybody_else_is_not(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        carol = await create_user(session)
        conversation = await _conversation(session, alice, bob)

        assert await _in_conversation(session, carol, conversation) is False

    async def test_unknown_conversation_is_not_an_error(self, session):
        alice = await create_user(session)

        await _as(session, alice)
        answer = (
            await session.exec(
                text("SELECT public.dm_in_conversation(:c)").bindparams(c=uuid.uuid4())
            )
        ).scalar_one()
        assert answer is False


class TestDeviceInConversation:
    async def test_a_members_device_belongs(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        conversation = await _conversation(session, alice, bob)
        device = await _device(session, bob)

        answer = (
            await session.exec(
                text("SELECT public.dm_device_in_conversation(:d, :c)").bindparams(
                    d=device.id, c=conversation.id
                )
            )
        ).scalar_one()
        assert answer is True

    async def test_an_outsiders_device_does_not(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        carol = await create_user(session)
        conversation = await _conversation(session, alice, bob)
        device = await _device(session, carol)

        answer = (
            await session.exec(
                text("SELECT public.dm_device_in_conversation(:d, :c)").bindparams(
                    d=device.id, c=conversation.id
                )
            )
        ).scalar_one()
        assert answer is False


class TestDeliverable:
    async def test_an_open_pair_is_deliverable(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        await _policy(session, alice, DmPolicy.public)
        await _policy(session, bob, DmPolicy.public)
        await _open_channel(session, alice, bob)

        assert await _deliverable(session, alice, bob) is True

    async def test_without_an_accepted_grant_it_is_not(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        await _policy(session, alice, DmPolicy.public)
        await _policy(session, bob, DmPolicy.public)

        assert await _deliverable(session, alice, bob) is False

    async def test_an_ignore_stops_delivery_one_way_only(self, session):
        alice = await create_user(session)
        bob = await create_user(session)
        await _policy(session, alice, DmPolicy.public)
        await _policy(session, bob, DmPolicy.public)
        await _open_channel(session, alice, bob)
        session.add(UserIgnore(user_id=bob.id, ignored_user_id=alice.id))
        await session.flush()

        # Nothing Alice sends arrives, and Bob may still reach her.
        assert await _deliverable(session, alice, bob) is False
        assert await _deliverable(session, bob, alice) is True

    async def test_the_sender_is_not_told(self, session):
        """An ignore never changes the answer the *actor* can see.

        ``dm_apparent_permission`` is what the sender's own request reads, and
        it stays ``open`` — the difference lives only in ``dm_deliverable``,
        which the send path asks about somebody else and never returns.
        """
        alice = await create_user(session)
        bob = await create_user(session)
        await _policy(session, alice, DmPolicy.public)
        await _policy(session, bob, DmPolicy.public)
        await _open_channel(session, alice, bob)
        session.add(UserIgnore(user_id=bob.id, ignored_user_id=alice.id))
        await session.flush()

        await _as(session, alice)
        apparent = (
            await session.exec(
                text("SELECT public.dm_apparent_permission(:t)").bindparams(t=bob.id)
            )
        ).scalar_one()
        assert apparent == "open"


class TestPairBoundary:
    """A direct-message conversation has exactly two members.

    Enforced on the table rather than in the endpoint: a pairwise ratchet has
    no meaning for a third party, and the membership policy on its own admits
    everybody the creator may message.
    """

    async def test_a_third_member_is_refused(self, session: AsyncSession) -> None:
        alice = await create_user(session)
        bob = await create_user(session)
        carol = await create_user(session)
        conversation = await _conversation(session, alice, bob)

        session.add(
            DmConversationMember(conversation_id=conversation.id, user_id=carol.id)
        )
        with pytest.raises(Exception, match="exactly two members"):
            await session.flush()
        await session.rollback()


class TestClaimingAPrekey:
    """Spending one key, and only one, and only where allowed."""

    async def _publish(
        self, session: AsyncSession, device: DmDevice, count: int
    ) -> None:
        for index in range(count):
            session.add(
                DmOneTimeKey(
                    device_id=device.id,
                    key_id=f"otk-{index}",
                    public_key=f"key-{index}".encode(),
                )
            )
        session.add(
            DmOneTimeKey(
                device_id=device.id,
                key_id="fb",
                public_key=b"fallback",
                fallback=True,
            )
        )
        await session.flush()

    async def _claim(
        self, session: AsyncSession, actor: User, device: DmDevice
    ) -> str | None:
        await _as(session, actor)
        row = (
            await session.exec(
                text("SELECT key_id FROM public.dm_claim_one_time_key(:d)").bindparams(
                    d=device.id
                )
            )
        ).first()
        return row[0] if row else None

    async def test_each_claim_spends_exactly_one(self, session: AsyncSession) -> None:
        alice = await create_user(session)
        bob = await create_user(session)
        await _policy(session, alice, DmPolicy.public)
        await _policy(session, bob, DmPolicy.public)
        await _open_channel(session, alice, bob)
        device = await _device(session, bob)
        await self._publish(session, device, 2)

        first = await self._claim(session, alice, device)
        second = await self._claim(session, alice, device)
        assert first != second

        remaining = (
            await session.exec(
                text(
                    "SELECT count(*) FROM public.dm_one_time_keys "
                    "WHERE device_id = :d AND fallback IS FALSE"
                ).bindparams(d=device.id)
            )
        ).scalar_one()
        assert remaining == 0

    async def test_the_fallback_answers_once_the_pool_is_empty(
        self, session: AsyncSession
    ) -> None:
        alice = await create_user(session)
        bob = await create_user(session)
        await _policy(session, alice, DmPolicy.public)
        await _policy(session, bob, DmPolicy.public)
        await _open_channel(session, alice, bob)
        device = await _device(session, bob)
        await self._publish(session, device, 1)

        await self._claim(session, alice, device)
        assert await self._claim(session, alice, device) == "fb"

    async def test_a_stranger_claims_nothing(self, session: AsyncSession) -> None:
        alice = await create_user(session)
        bob = await create_user(session)
        device = await _device(session, bob)
        await self._publish(session, device, 2)

        assert await self._claim(session, alice, device) is None
