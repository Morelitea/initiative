"""Connections and message requests — what two accounts have agreed.

Both live in ``contact_grants``, one row per unordered pair per kind, and they
do different jobs. A **connection** satisfies every ``DmPolicy`` and opens
nothing on its own; an accepted **message** grant is what opens the channel.
So a pair on ``private`` needs both.

Two rules here are worth finding when you come back to this module:

* ``initial_message_state`` — a message grant between connected accounts starts
  accepted. That is a statement about what a connection currently *means*, not
  about messaging, and it is the one place to delete when a connection carries
  anything else.
* ``revoke_stale_message_grants`` — a grant lives only while the pair could ask
  each other today. Five events take a leg of ``can_ask`` away, and all five
  run the same test rather than each carrying a rule of its own.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.platform.contact_grant import (
    ContactGrant,
    ContactGrantKind,
    ContactGrantState,
    canonical_pair,
)
from app.models.platform.user_ignore import UserIgnore
from app.schemas.platform.dm import (
    ContactGrantRead,
    ContactGrantsResponse,
)


class ContactGrantError(Exception):
    """Raised with a message code the endpoint turns into a status."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def initial_message_state(connected: bool) -> ContactGrantState:
    """The state a message grant is born in.

    Connected accounts get an accepted one: asking somebody to connect and then
    asking them again for permission to say hello is a consent step with no
    decision in it. Not a rule about messaging — a rule about what a connection
    currently means. When a connection carries anything besides messaging, this
    returns ``pending`` again and nothing else moves.
    """
    return ContactGrantState.accepted if connected else ContactGrantState.pending


async def _get(
    session: AsyncSession, a: int, b: int, kind: ContactGrantKind
) -> ContactGrant | None:
    low, high = canonical_pair(a, b)
    return await session.get(ContactGrant, (low, high, kind))


async def are_connected(session: AsyncSession, a: int, b: int) -> bool:
    row = await _get(session, a, b, ContactGrantKind.connection)
    return row is not None and row.state is ContactGrantState.accepted


async def _may_connect(session: AsyncSession, target_id: int) -> bool:
    """Whether the caller may send this account a connection request.

    ``dm_may_connect`` reads the caller from the request context, so this asks
    about the caller and one other account and cannot be pointed elsewhere.
    """
    return (
        await session.exec(
            text("SELECT public.dm_may_connect(:t)").bindparams(t=target_id)
        )
    ).scalar_one()


async def _may_message(session: AsyncSession, target_id: int) -> bool:
    """Whether the caller and this account could open a channel today.

    The same answer the profile shows, from the same function — ``denied``
    covers every refusal, including being ignored, which the caller is not told
    apart from the rest.
    """
    permission = (
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=target_id)
        )
    ).scalar_one()
    return permission in ("may_request", "open")


async def _pair_still_allowed(session: AsyncSession, a: int, b: int) -> bool:
    """``public.dm_mutual_ask`` for a pair that need not involve the caller.

    Only the system engine may ask this, which is why the sweep runs there.
    """
    return (
        await session.exec(
            text("SELECT public.dm_mutual_ask(:a, :b)").bindparams(a=a, b=b)
        )
    ).scalar_one()


async def list_for(
    session: AsyncSession, *, user_id: int, kind: ContactGrantKind
) -> list[ContactGrant]:
    """Every grant of one kind this account is a party to.

    Rows whose other party the reader ignores are dropped here, so the pending
    list of somebody they have stopped hearing from is not a way through.
    """
    rows = (
        await session.exec(
            select(ContactGrant)
            .where(
                ContactGrant.kind == kind,
                or_(
                    ContactGrant.user_id_low == user_id,
                    ContactGrant.user_id_high == user_id,
                ),
            )
            .order_by(col(ContactGrant.created_at).desc())
        )
    ).all()
    if not rows:
        return []

    ignored = set(
        (
            await session.exec(
                select(UserIgnore.ignored_user_id).where(UserIgnore.user_id == user_id)
            )
        ).all()
    )
    return [
        row
        for row in rows
        if other_party(row, user_id) not in ignored
        # A request from an account that ignores the reader is stored and never
        # surfaced to them; it becomes acceptable if that is ever lifted.
        and not (
            row.state is ContactGrantState.pending
            and row.requested_by != user_id
            and other_party(row, user_id) in ignored
        )
    ]


def other_party(grant: ContactGrant, user_id: int) -> int:
    return grant.user_id_high if grant.user_id_low == user_id else grant.user_id_low


async def request(
    session: AsyncSession,
    *,
    actor_id: int,
    target_id: int,
    kind: ContactGrantKind,
) -> ContactGrant:
    """Ask for a connection, or for permission to message.

    A crossing request — the other party asking while yours is pending — is a
    primary-key collision rather than a race, and it means both of them wanted
    it, so it is turned into an accept.

    An account that ignores the actor still gets the row: it is stored, never
    surfaced to them, and becomes acceptable if they ever stop. Refusing here
    would answer a question this feature does not answer.
    """
    from app.core.messages import ContactGrantMessages

    if actor_id == target_id:
        raise ContactGrantError(ContactGrantMessages.CANNOT_GRANT_SELF)

    existing = await _get(session, actor_id, target_id, kind)
    if existing is not None:
        if existing.state is ContactGrantState.accepted:
            return existing
        if existing.requested_by == actor_id:
            return existing
        return await accept(session, actor_id=actor_id, other_id=target_id, kind=kind)

    allowed = (
        await _may_connect(session, target_id)
        if kind is ContactGrantKind.connection
        else await _may_message(session, target_id)
    )
    if not allowed:
        raise ContactGrantError(ContactGrantMessages.CANNOT_REACH)

    low, high = canonical_pair(actor_id, target_id)
    state = (
        initial_message_state(await are_connected(session, actor_id, target_id))
        if kind is ContactGrantKind.message
        else ContactGrantState.pending
    )
    now = datetime.now(timezone.utc)
    grant = ContactGrant(
        user_id_low=low,
        user_id_high=high,
        kind=kind,
        state=state,
        requested_by=actor_id,
        created_at=now,
        responded_at=now if state is ContactGrantState.accepted else None,
    )
    session.add(grant)
    await session.commit()
    await session.refresh(grant)
    return grant


async def accept(
    session: AsyncSession,
    *,
    actor_id: int,
    other_id: int,
    kind: ContactGrantKind,
) -> ContactGrant:
    """Say yes to a request somebody else made.

    Accepting a connection also opens the pair's message grant, per
    ``initial_message_state`` — one act, one consent, and one notification.
    """
    from app.core.messages import ContactGrantMessages

    grant = await _get(session, actor_id, other_id, kind)
    if grant is None or grant.requested_by == actor_id:
        raise ContactGrantError(ContactGrantMessages.NO_REQUEST)
    if grant.state is ContactGrantState.accepted:
        return grant

    grant.state = ContactGrantState.accepted
    grant.responded_at = datetime.now(timezone.utc)
    session.add(grant)

    if kind is ContactGrantKind.connection:
        await _open_message_grant(session, actor_id, other_id, grant.requested_by)

    await session.commit()
    await session.refresh(grant)
    return grant


async def _open_message_grant(
    session: AsyncSession, a: int, b: int, requested_by: int
) -> None:
    """Give a newly connected pair their channel.

    Flips an in-flight pending request rather than colliding with it: the
    connection answers the same question it was asking.
    """
    existing = await _get(session, a, b, ContactGrantKind.message)
    now = datetime.now(timezone.utc)
    if existing is not None:
        if existing.state is not ContactGrantState.accepted:
            existing.state = ContactGrantState.accepted
            existing.responded_at = now
            session.add(existing)
        return
    low, high = canonical_pair(a, b)
    session.add(
        ContactGrant(
            user_id_low=low,
            user_id_high=high,
            kind=ContactGrantKind.message,
            state=ContactGrantState.accepted,
            requested_by=requested_by,
            created_at=now,
            responded_at=now,
        )
    )


async def remove(
    session: AsyncSession,
    *,
    actor_id: int,
    other_id: int,
    kind: ContactGrantKind,
) -> None:
    """Decline, cancel, disconnect or close — one verb, one delete.

    There is no ``declined`` state to store: the pair is back where it started
    and either may ask again. Removing a *connection* re-tests the pair's
    message grant rather than deleting it: a connection is a leg of ``can_ask``,
    not a rank above the others, so two co-members who un-connect keep talking.
    """
    grant = await _get(session, actor_id, other_id, kind)
    if grant is None:
        return
    await session.delete(grant)
    await session.flush()
    if kind is ContactGrantKind.connection:
        await _revoke_pair_if_stale(session, actor_id, other_id)
    await session.commit()


async def _revoke_pair_if_stale(
    session: AsyncSession, caller_id: int, other_id: int
) -> None:
    """Re-test one pair after a connection between them went away.

    The caller is one of the two, so the question is theirs to ask and the row
    is theirs to delete.
    """
    grant = await _get(session, caller_id, other_id, ContactGrantKind.message)
    if grant is None:
        return
    if not await _may_message(session, other_id):
        await session.delete(grant)
        await session.flush()


async def revoke_stale_message_grants(session: AsyncSession, *, user_id: int) -> int:
    """Drop every message grant this account could no longer form today.

    Called wherever a leg of ``can_ask`` goes away — a policy change, a
    community switched off, a membership dropped, a community suspended, a
    connection removed. All five ask the one question rather than each carrying
    a rule of its own, so a grant is revoked for the same reason it would be
    refused.

    Runs on the system engine. The pairs need not involve whoever is making the
    request — removing somebody from a community re-tests *their* grants — and
    both the pairwise test and those rows are out of the request path's reach.
    Call it after the change that prompted it has committed: this commits on its
    own, so a caller that rolls back afterwards would have revoked for nothing.

    Returns how many were dropped, so a caller can decide whether to signal.
    """
    from app.db.session import AdminSessionLocal

    dropped = 0
    async with AdminSessionLocal() as admin_session:
        grants = (
            await admin_session.exec(
                select(ContactGrant).where(
                    ContactGrant.kind == ContactGrantKind.message,
                    or_(
                        ContactGrant.user_id_low == user_id,
                        ContactGrant.user_id_high == user_id,
                    ),
                )
            )
        ).all()
        for grant in grants:
            if not await _pair_still_allowed(
                admin_session, grant.user_id_low, grant.user_id_high
            ):
                await admin_session.delete(grant)
                dropped += 1
        if dropped:
            await admin_session.commit()
    return dropped


async def resolve_handle(
    session: AsyncSession, *, username: str, discriminator: int
) -> int:
    """The account id behind a handle, for a connection request.

    One answer for every miss: a handle nobody holds and a handle belonging to
    somebody unreachable both raise the same code, so the endpoint is not a way
    to sweep the discriminator space for accounts that exist.
    """
    from app.core.messages import ContactGrantMessages

    row = (
        await session.exec(
            text(
                "SELECT id FROM public.user_profiles "
                "WHERE lower(username) = lower(:u) AND discriminator = :d"
            ).bindparams(u=username, d=discriminator)
        )
    ).first()
    if row is None:
        raise ContactGrantError(ContactGrantMessages.HANDLE_NOT_FOUND)
    return row[0]


async def to_reads(
    session: AsyncSession, *, user_id: int, grants: list[ContactGrant]
) -> ContactGrantsResponse:
    """Group a reader's grants into accepted, incoming and outgoing."""
    if not grants:
        return ContactGrantsResponse(accepted=[], incoming=[], outgoing=[])

    others = {other_party(grant, user_id) for grant in grants}
    profiles = {
        row[0]: row
        for row in (
            await session.exec(
                text(
                    "SELECT id, username, discriminator, avatar_url "
                    "FROM public.user_profiles WHERE id = ANY(:ids)"
                ).bindparams(ids=list(others))
            )
        ).all()
    }

    accepted: list[ContactGrantRead] = []
    incoming: list[ContactGrantRead] = []
    outgoing: list[ContactGrantRead] = []
    for grant in grants:
        other = other_party(grant, user_id)
        profile = profiles.get(other)
        if profile is None:
            continue
        read = ContactGrantRead(
            user_id=other,
            username=profile[1],
            discriminator=profile[2],
            avatar_url=profile[3],
            state=grant.state.value,
            outgoing=grant.requested_by == user_id,
            created_at=grant.created_at,
            responded_at=grant.responded_at,
        )
        if grant.state is ContactGrantState.accepted:
            accepted.append(read)
        elif read.outgoing:
            outgoing.append(read)
        else:
            incoming.append(read)
    return ContactGrantsResponse(
        accepted=accepted, incoming=incoming, outgoing=outgoing
    )
