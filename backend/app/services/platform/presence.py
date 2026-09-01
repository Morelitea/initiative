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

It takes three facts to say how someone appears, and the roll holds all three
so that "how does this person appear" is one lookup with one answer, rather
than a rule each of the several surfaces that draw a dot would have to apply
for itself:

* whether anything is open, which only the sockets know;
* what the person picked — ``users.presence``, which is a column because it
  outlives every socket, and which a connecting socket brings with it;
* when they last did something, which is what separates someone at their
  keyboard from someone who left a tab open. That only ever narrows ``online``
  — to ``idle`` — because every other value is something a person said, and an
  inference does not talk over a statement. Picking ``idle`` outright is one of
  those statements, and holds however busy the keyboard is.

Bounded the way the other in-memory rolls are: these are one process's own
sockets. Where the API runs as more than one worker each holds a share, so this
can say "offline" about someone another worker is serving — the direction that
tells a reader less rather than more.
"""

from time import monotonic
from typing import Dict, Iterable, Set

from app.models.platform.user import Presence

#: How long a person's tabs go without a sign of them before they read as idle.
#: Long enough to sit through reading a document, short enough that a tab left
#: open overnight does not claim someone is at it.
IDLE_AFTER_SECONDS = 10 * 60


class OnlineRoll:
    """Counted per user rather than per socket, so two tabs are one person."""

    def __init__(self) -> None:
        # user_id -> how many of that user's sockets are open on this process.
        self._sockets: Dict[int, int] = {}
        # user_id -> what they picked, for as long as they have something open.
        # Dropped with their last socket: a preference nobody can be shown is
        # the column's to keep, not this roll's.
        self._chosen: Dict[int, Presence] = {}
        # user_id -> monotonic time of the last sign of them. Monotonic because
        # only the gap matters, and a clock that steps must not move it.
        self._last_active: Dict[int, float] = {}

    def arrived(self, user_id: int, chosen: Presence = Presence.online) -> None:
        self._sockets[user_id] = self._sockets.get(user_id, 0) + 1
        # The newest socket read the column most recently, so it wins.
        self._chosen[user_id] = chosen
        # Opening a tab is somebody doing something.
        self._last_active[user_id] = monotonic()

    def left(self, user_id: int) -> None:
        remaining = self._sockets.get(user_id, 0) - 1
        if remaining > 0:
            self._sockets[user_id] = remaining
        else:
            self._sockets.pop(user_id, None)
            self._chosen.pop(user_id, None)
            self._last_active.pop(user_id, None)

    def chose(self, user_id: int, chosen: Presence) -> None:
        """Follow a change made from an open tab.

        Ignored for someone with nothing open: they appear offline either way,
        and their next socket brings the column's value with it.
        """
        if user_id in self._sockets:
            self._chosen[user_id] = chosen

    def active(self, user_id: int) -> None:
        """Note a sign of them, from any one of their tabs.

        Per user rather than per socket: a person reading in one window is at
        their keyboard whatever the other windows are doing, and the newest
        sign of them is the one that answers that.
        """
        if user_id in self._sockets:
            self._last_active[user_id] = monotonic()

    def presence_of(self, user_id: int) -> Presence:
        """How this account appears to anyone reading it right now."""
        if user_id not in self._sockets:
            return Presence.offline
        chosen = self._chosen.get(user_id, Presence.online)
        if chosen is not Presence.online:
            return chosen
        since = monotonic() - self._last_active.get(user_id, 0.0)
        return Presence.idle if since >= IDLE_AFTER_SECONDS else Presence.online

    def is_online(self, user_id: int) -> bool:
        """Whether this account appears at all — any of the shown states.

        Idle counts: they are here, they are just not typing.
        """
        return self.presence_of(user_id) is not Presence.offline

    def online_users(self, user_ids: Iterable[int]) -> Set[int]:
        """Which of these accounts are online, for a page of them at a time."""
        return {user_id for user_id in user_ids if self.is_online(user_id)}


#: The one roll every channel feeds and every reader asks.
online = OnlineRoll()
