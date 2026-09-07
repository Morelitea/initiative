"""The account's use of the per-user signal channel.

The signed-in account is read once, when a tab boots, and then only when
something asks for it again. Most of what it holds cannot change underneath
that — but some of it can, and not always by anything its owner did: somebody
is added to a community by an admin or a group sync, a community lists itself,
a platform role is granted. From that moment the tab is deciding on an answer
that is no longer true, and would go on doing so until it next loaded.

This is the poke that fixes it. Like every frame here it carries **nothing**:
it says "your account changed", the client re-reads ``GET /users/me``, and that
request — authorized by being that account — is the only place anything is
decided. Nothing about what changed crosses the wire, so a frame delivered to
the wrong socket would tell its reader nothing they could not already ask for
themselves.

The socket, the after-commit queueing and the cross-worker bus belong to
:mod:`app.services.platform.user_stream`, shared with the inbox channel.
"""

from typing import Any

from app.services.platform import user_stream

#: What the client switches on to tell this channel from the inbox one.
RESOURCE = "account"


async def signal_account(user_id: int, action: str = "changed") -> None:
    """Tell one user's open tabs to re-read their own account."""
    await user_stream.publish(user_id, user_stream.build_frame(RESOURCE, action))


def queue_account_signal(
    session: Any, user_id: int | None, action: str = "changed"
) -> None:
    """Note that this session changed what ``/users/me`` would answer.

    Sent once the transaction commits, never before: a frame that arrives ahead
    of the COMMIT hands the client the state it is replacing, and nothing polls
    behind it closely enough to correct that.
    """
    user_stream.queue_frame(session, user_id, user_stream.build_frame(RESOURCE, action))


def queue_for_members(session: Any, user_ids: Any, action: str = "changed") -> None:
    """Signal a set of accounts at once — a whole community's members.

    Listing a community changes the answer for everybody already in it, which
    is the one fan-out this channel has. Callers pass the whole set: each frame
    goes to this worker's sockets and onto the bus for every other worker's,
    and a caller that narrowed to its own sockets first would be answering for
    processes it cannot see.
    """
    for user_id in user_ids:
        queue_account_signal(session, user_id, action)
