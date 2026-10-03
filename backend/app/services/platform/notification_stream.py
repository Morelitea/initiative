"""The inbox's use of the per-user signal channel.

The bell is a *personal* surface: a user's notifications span every guild they
belong to (and some, like ``user_pending_approval``, belong to no guild at
all), so this is addressed by user id and carries no guild. That is what makes
it a different object from :mod:`app.services.content_sockets`, whose rooms are
``(guild_id, kind, id)`` and whose sockets only exist while a tab sits
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


def queue_signal(session: Any, user_id: int | None, action: str = "changed") -> None:
    """Note that this session changed ``user_id``'s inbox.

    Nothing is sent yet — the frame goes out once the transaction commits, so
    one that rolls back pokes nobody.
    """
    user_stream.queue_frame(session, user_id, user_stream.build_frame(RESOURCE, action))


#: The desktop app's channel: "show these lines as system notifications". Its
#: own resource rather than an action on the inbox's, so a client that does not
#: alert passes over it rather than reading its inbox again.
ALERT_RESOURCE = "alert"


def queue_alert(session: Any, user_id: int, notification_id: int) -> None:
    """Ask ``user_id``'s desktop apps to announce one bell line, once this
    session commits. Lines opened in one transaction share a frame. The frame
    names them and says nothing about them: the app reads each from
    ``GET /notifications/{id}/alert``."""
    frame = user_stream.queue_frame(
        session,
        user_id,
        user_stream.build_frame(ALERT_RESOURCE, "created", {"notifications": []}),
    )
    if frame is not None and notification_id not in frame["ids"]["notifications"]:
        frame["ids"]["notifications"].append(notification_id)
