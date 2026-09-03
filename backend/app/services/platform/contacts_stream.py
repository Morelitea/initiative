"""Connections, requests and the ignore list, on the per-user signal channel.

The third channel over the shared transport, beside the inbox
(:mod:`app.services.platform.notification_stream`) and the account
(:mod:`app.services.platform.account_stream`). A frame carries **nothing**: it
says one of these lists moved, the client re-reads through the ordinary
endpoints, and those requests — own-row, or answered by
``public.dm_apparent_permission`` — are where anything is decided.

Its own channel rather than an arm on the account one, because an ``account``
frame means "re-read ``GET /users/me``", and a membership change would
otherwise drag a refetch of three contact lists behind it.

**Being ignored sends nothing.** The account that was ignored is signalled
neither when it happens, nor when it is lifted, nor for a request of theirs
that is filed where nobody will see it. A frame is as much a tell as a
notification, so where a real event coincides with an ignore — a request from
somebody the recipient ignores — only the requester is signalled, and each
frame carries exactly the state its reader may know about.
"""

from typing import Any, Iterable

from app.services.platform import user_stream

#: What the client switches on to tell this channel from the other two.
RESOURCE = "contacts"


async def signal_contacts(user_id: int, action: str = "changed") -> None:
    """Tell one account's open tabs to re-read their contact lists."""
    await user_stream.publish(user_id, user_stream.build_frame(RESOURCE, action))


def queue_contacts_signal(
    session: Any, user_id: int | None, action: str = "changed"
) -> None:
    """Note that this session changed what those lists would answer.

    Sent once the transaction commits, never before: a frame that arrives ahead
    of the COMMIT hands the client the state it is replacing.
    """
    user_stream.queue_frame(session, user_id, user_stream.build_frame(RESOURCE, action))


def queue_for_present(
    session: Any, user_ids: Iterable[int], action: str = "changed"
) -> None:
    """Signal a set of accounts, narrowed to the ones with a socket here.

    Revoking a community's worth of channels would otherwise cost the size of
    the membership rather than the number of people present. Anybody not here
    finds the new state on their next read, which is what a content-free frame
    was standing in for anyway.
    """
    connected = user_stream.stream.connected_users()
    for user_id in user_ids:
        if user_id in connected:
            queue_contacts_signal(session, user_id, action)
