---
icon: lucide/message-square
---

# Messages

Sometimes the thing you need to say really doesn't belong on a task.

**Messages** are private one-to-one conversations. They're end-to-end encrypted, which means what you write can be read by the person you sent it to and by absolutely nobody else — not a community admin, not whoever runs the server, and not us.

Open them from the **Initiative logo** in the top-left corner, then **My Messages**.

!!! info "One to one, on purpose"
    There are no group messages, and there aren't going to be — because you've already got somewhere better to have that conversation.

    **Everything in Initiative has comments.** Projects, tasks, documents, queues, counters, calendars, dashboards, the lot. So the discussion about a thing lives *on* that thing, right where the next person will find it, instead of forty messages upstream of where they started reading.

    **And comments are searchable.** Half-remember somebody saying something about the venue deposit? Search it. It comes back. This is a genuinely nice feeling and we recommend it.

    Which is the real trouble with a group chat: somebody pastes the thing that should have been a document, and six months later everyone is scrolling for it, and Jenny has left, and somebody is looking at the printer in a way the printer has done nothing to deserve.

    Messages are for the quiet word on the side. Different job, and the one they're good at.

!!! screenshot "My Messages"
    **Show:** the Messages page with a conversation open — the list of people on the left, a thread on the right, and the encrypted notice under the title.

    Save as `en/images/guides/my-messages.png`, then replace this box with:
    `![My Messages](../images/guides/my-messages.png)`

## Who can reach you

You decide, under **User settings → Privacy**. The setting covers who may *ask* — nobody starts a conversation with you outright, whichever you pick:

| Setting | Who can ask |
|---|---|
| **Private** | Nobody. |
| **My communities** | People you share a community with — narrowable to particular communities. |
| **Anyone** | Anybody on Initiative, by your handle. |

Every one of these ends in a **request** you accept or decline. *Anyone* widens who may ask; it never lets somebody write to you unasked.

!!! info "New accounts start Private"
    Which means nobody can reach you until you open it up — and your [My Contacts](your-space.md#my-contacts) sections start empty for the same reason. Whoever runs your server picks the setting new accounts are created with, and the shipped default is **Private**. Changing it later affects only accounts made after the change; it never opens or closes an existing one.

Whatever you choose, a **connection** always lets the two of you message each other. That's the point of one.

!!! screenshot "Privacy settings"
    **Show:** User settings → Privacy, with the three choices and the per-community switches under *My communities*.

    Save as `en/images/guides/privacy-settings.png`, then replace this box with:
    `![Privacy settings](../images/guides/privacy-settings.png)`

## Connections

A connection is a mutual link between two accounts. Someone asks, you accept, and from then on you can reach each other — even if you stop sharing a community, or never shared one.

Add someone by their full handle, including the number (`sam#1234`), from **User settings → Privacy → Connections**, or from the actions menu on their row in **My Contacts** or on their profile.

Removing a connection asks you to confirm, because it may take your ability to message each other with it — Initiative tells you which case you're in before you decide.

## Message requests

If you're not connected, you send a **request to message**. A request is exactly that: it carries no text. The other person sees that you'd like to talk, and nothing else — so a request can't be used to say something to someone who hasn't agreed to hear it.

Accept it and a conversation opens for both of you. Decline it and the request simply goes away — there's no "declined" state left hanging over anybody, and either of you can ask again another time.

Requests waiting on you are under **User settings → Privacy → Pending**, and on **My Contacts**.

## Ignoring someone

Ignoring is the firm answer, for when the polite one hasn't worked. From the actions menu on any profile or contact row, choose **Ignore**.

An ignored account stops reaching you entirely: no notification when they mention, reply to, or react to you, and nothing they send arrives — messages, message requests, connection requests. They're not told. You'll still see each other's activity in communities you share, and you can both use every tool normally, because ignoring is about contact rather than about work.

Nothing is deleted. Stop ignoring them and everything is exactly where it was.

## Your messages live on your devices

This is the bit to read before you rely on it, because it genuinely works differently from everything else in Initiative and it surprises people.

A message is delivered to your devices and then **deleted from the server**. There is no copy in the middle for a new device to catch up from. So:

- **Each device keeps its own copy** of a conversation.
- **A device that wasn't there doesn't have the history.** Sign in on a new laptop and your conversations are there, but they start from the moment that laptop joined them.
- **Signing out takes this device's copy with it.** Exactly what you want on a shared computer, and exactly what you don't want if you were hoping to read them again — so keep the conversations that matter on a device you stay signed in to.

If the person you're writing to has never opened Messages, there's no device to deliver to yet, and Initiative tells you so rather than pretending the message went.

## Notifications

You'll be told that somebody messaged you, and how many times. Never what they said, because nothing outside your own devices is capable of telling you that.

Turn it on or off under **User settings → Notifications → Direct messages**, like any other category. A flurry of messages arrives as one notification rather than twenty, because twenty would be a punishment.

See [Notifications](notifications.md).

## What this means for community admins

Messages are **not** community content. A community admin can reach everything in their community — every project, document, and task — and that authority stops at the edge of a private conversation. Messages don't appear in exports, they can't be searched, and there is nothing to moderate, because there is nothing to read.

The tools that *do* work are the ones above: people control who can reach them, and ignoring ends contact without needing anyone's help. If an account is behaving badly, report the account — see [Reporting a problem](../security/reporting-a-problem.md).

## Related

- [Private messages](../security/private-messages.md) — what encryption does and doesn't cover, and what can be handed over.
- [Your space](your-space.md#my-contacts) — finding the people you know.
- [Notifications](notifications.md) — choosing what you're told about.
