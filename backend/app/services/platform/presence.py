"""Who has Initiative open — the person, not the place.

Presence is a fact about an account, not about a guild: someone with a tab open
is online whether that tab is a guild they share with whoever is asking, a
guild they don't, or no guild at all. So it lives here rather than inside any
one channel's connection manager, and every channel that proves a person is
present feeds the same roll.

Two do. The guild events socket (``app.services.realtime``) only exists while a
tab sits inside a guild. The notification stream
(``app.services.platform.notification_stream``) has no guild in its address and
is open on every page for as long as someone is signed in, which is what makes
it the signal that actually answers the question.

Bounded the way the other in-memory rolls are: these are one process's own
sockets. Where the API runs as more than one worker each holds a share, so this
can say "no" about someone another worker is serving. It drives a dot beside a
name — a hint, not a fact anything depends on.
"""

from typing import Dict, Iterable, Set


class OnlineRoll:
    """Counted per user rather than per socket, so two tabs are one person."""

    def __init__(self) -> None:
        # user_id -> how many of that user's sockets are open on this process.
        self._sockets: Dict[int, int] = {}

    def arrived(self, user_id: int) -> None:
        self._sockets[user_id] = self._sockets.get(user_id, 0) + 1

    def left(self, user_id: int) -> None:
        remaining = self._sockets.get(user_id, 0) - 1
        if remaining > 0:
            self._sockets[user_id] = remaining
        else:
            self._sockets.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._sockets

    def online_users(self, user_ids: Iterable[int]) -> Set[int]:
        """Which of these accounts are online, for a page of them at a time."""
        return {user_id for user_id in user_ids if user_id in self._sockets}


#: The one roll every channel feeds and every reader asks.
online = OnlineRoll()
