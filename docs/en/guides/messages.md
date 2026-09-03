---
icon: lucide/message-square
---

# Messages

Sometimes the thing you need to say doesn't belong on a task. **Messages** are private one-to-one conversations between two people — end-to-end encrypted, so what you write can be read by the person you sent it to and by nobody else. Not by a community admin, not by whoever runs the server, and not by us.

Open them from the **Initiative logo** in the top-left corner, then **My Messages**.

!!! info "One to one, on purpose"
    There are no group messages, and there won't be. Group conversations belong in a community, where they can be found, shared, and handed on when someone leaves. Messages are for the quiet word on the side.

!!! screenshot "My Messages"
    **Show:** the Messages page with a conversation open — the list of people on the left, a thread on the right, and the encrypted notice under the title.

    Save as `en/images/guides/my-messages.png`, then replace this box with:
    `![My Messages](../images/guides/my-messages.png)`

## Who can reach you

You decide, under **User settings → Privacy**. The setting covers who may *ask* — nobody starts a conversation with you outright, whichever you pick:

| Setting | Who can ask |
|---|---|
| **Private** | Nobody. |
| **My communities** | People you share a community with — and you can narrow it to particular communities. |
| **Anyone** | Anybody on Initiative, by your handle. |

Every one of these ends in a **request** you accept or decline. *Anyone* removes the restriction on who may ask — it doesn't let anybody write to you unasked.

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

Ignoring is the firm answer. From the actions menu on any profile or contact row, choose **Ignore**.

An ignored account stops reaching you entirely: no notification when they mention, reply to, or react to you, and nothing they send arrives — messages, message requests, connection requests. They're not told. You'll still see each other's activity in communities you share, and you can both use every tool normally, because ignoring is about contact rather than about work.

Nothing is deleted. Stop ignoring them and everything is exactly where it was.

## Your messages live on your devices

This is the part worth knowing before you rely on it, because it works differently from everything else in Initiative.

A message is delivered to your devices and then **deleted from the server**. There is no copy in the middle for a new device to catch up from. So:

- **Each device keeps its own copy** of a conversation.
- **A device that wasn't there doesn't have the history.** Sign in on a new laptop and your conversations are there, but they start from the moment that laptop joined them.
- **Signing out takes this device's messages with it.** That's the right answer on a shared computer, and the wrong one if you wanted them back — so keep the conversations you care about on a device you stay signed in to.

If the person you're writing to has never opened Messages, there's no device to deliver to yet, and Initiative tells you so rather than pretending the message went.

## Notifications

You'll be told that someone messaged you and how many times — never what they said, because nothing outside your own devices could say. Turn it on or off under **User settings → Notifications → Direct messages**, like any other category. A flurry of messages arrives as one notification rather than twenty.

See [Notifications](notifications.md).

## What this means for community admins

Messages are **not** community content. A community admin can reach everything in their community — every project, document, and task — and that authority stops at the edge of a private conversation. Messages don't appear in exports, they can't be searched, and there is nothing to moderate, because there is nothing to read.

The tools that *do* work are the ones above: people control who can reach them, and ignoring ends contact without needing anyone's help. If an account is behaving badly, report the account — see [Reporting a problem](../security/reporting-a-problem.md).

## Related

- [Private messages](../security/private-messages.md) — what encryption does and doesn't cover, and what can be handed over.
- [Your space](your-space.md#my-contacts) — finding the people you know.
- [Notifications](notifications.md) — choosing what you're told about.
