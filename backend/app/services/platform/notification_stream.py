"""The inbox's use of the per-user signal channel.

The bell is a *personal* surface: a user's notifications span every guild they
belong to (and some, like ``user_pending_approval``, belong to no guild at
all), so this is addressed by user id and carries no guild. That is what makes
it a different object from :mod:`app.services.realtime`, whose rooms are
``(guild_id, initiative_id)`` and whose sockets only exist while a tab sits
inside a guild.

The socket, the after-commit queueing and the cross-worker bus are not this
module's — they are :mod:`app.services.platform.user_stream`, shared with the
account channel. What is here is the inbox's half: what its frames mean and
who sends them.

Like every realtime channel here, a frame is a **content-free invalidation
signal**: it says "your inbox changed", never what changed. The client refetches
``GET /notifications/``, and that request — authenticated and scoped to
``current_user`` — is the authorization gate.
"""

from typing import Any

from app.services.platform import user_stream

#: What the client switches on to tell this channel from the account one.
RESOURCE = "notification"


async def signal_user(user_id: int, action: str = "changed") -> None:
    """Tell one user's open tabs that their inbox moved.

    ``ids`` is deliberately empty: the inbox is addressed by *who is asking*,
    so there is nothing for the client to name in its refetch and nothing here
    worth carrying. ``action`` distinguishes a new arrival from a read-state
    change only so a client could treat them differently; both mean "refetch".
    """
    await user_stream.publish(user_id, user_stream.build_frame(RESOURCE, action))


def queue_signal(session: Any, user_id: int | None, action: str = "changed") -> None:
    """Note that this session changed ``user_id``'s inbox.

    Nothing is sent yet — the frame goes out once the transaction commits, so
    one that rolls back pokes nobody.
    """
    user_stream.queue_frame(session, user_id, user_stream.build_frame(RESOURCE, action))
