---
icon: lucide/lock
---

# Private messages

Direct messages in Initiative are **end-to-end encrypted**. A message is locked on the device that writes it and only opened on the devices it was sent to, so everywhere in between — the server, the backups, the logs — it's just a jumble.

This page explains what that covers, what it doesn't, and why your messages behave a little differently from the rest of Initiative. If you just want to get on with using them, [the guide](../guides/messages.md) is the friendlier read.

## What stays private

**Everything you write.** The keys that open a message live on the devices in the conversation, and nowhere else. We don't have them, we can't make them, and there's nowhere for us to ask.

That's worth saying carefully, because plenty of services promise not to look. This isn't a promise about our behaviour — it's a fact about how the thing is built. There's no admin setting that reveals a thread, no support tool that opens one, and no senior enough person to overrule it. When we say we can't read your messages, we mean there's nothing there for us to read.

## What isn't hidden

Encryption keeps *what you said* private. It doesn't hide *that you said something*.

The server has to know where to deliver a message, so it can tell:

- **Which accounts have a conversation open**, and when it started.
- **Roughly when messages moved**, and how many.
- **The devices on an account**, and when each was last used.
- **The ordinary account details**: your handle, your email address, when you joined.

That's true of every messaging service, encrypted or not. It's worth knowing if the fact that two people are talking is itself the sensitive part — encryption isn't the tool for that, and choosing who can reach you is.

## What isn't kept at all

- **Delivered messages are deleted.** Once your device has picked a message up, the server's copy is gone. What's left waiting is only what hasn't been collected yet.
- **Nothing is indexed.** There's no search across messages, no analytics, no scanning, and nothing feeding a model. None of that is possible on text nobody can read.

## If someone asks us for your messages

It happens — a legal request, an investigation, an insistent employer. The answer is short, and it's the same one every time: we can say **whether** two accounts have a conversation and roughly when, because delivering a message requires knowing that much. We cannot produce a single word of what was said, because no copy exists that anyone but the two of you can open.

The same applies if you run Initiative yourself. Your database holds your community's projects and documents in full, and your members' conversations as text you have no key to. There's nothing you could be pressed into handing over, which is a quieter kind of relief than it sounds.

The formal version of this, with the rest of the compliance picture, is in [Data & compliance](data-and-compliance.md#what-could-be-handed-over).

## Why your history follows your devices

These two things are connected. If the server kept a readable archive so a new phone could catch up on old conversations, that archive would be exactly the thing somebody would ask for.

So there isn't one. Each device keeps its own copy, a device that wasn't there doesn't have the older messages, and signing out takes that device's copy with it. It's a genuine cost, and it's what buys everything above. See [Your messages live on your devices](../guides/messages.md#your-messages-live-on-your-devices).

## Messages aren't community content

If you run a community, this is the part to know: your authority over your community is real and it stops at the edge of a private conversation.

- Messages **aren't part of a community**, so they're not in its exports, its search, or its trash.
- There's **nothing to moderate**, because there's nothing to read — by anyone, at any level.
- The controls that do work belong to the people in the conversation: who may ask to message them, and [ignoring an account](../guides/messages.md#ignoring-someone), which ends contact at once and tells the other person nothing.

So if somebody is behaving badly, the thing to report is the **account**, not the message — see [Reporting a problem](reporting-a-problem.md).

## For anyone taking a closer look

If you're the person who has to answer for this choice to a board, a client, or your own conscience:

- Messages use the **Double Ratchet** — the design behind Signal's — through a well-established, independently audited open-source implementation. We didn't invent a cipher.
- Conversations are **one-to-one only**. Group messaging isn't offered, so no key is ever shared beyond two people.
- There are **no recovery keys and no exceptional access**. Nothing is held in reserve, so nothing can be lost or demanded.
- The code is **open source**, like the rest of Initiative. You can read it rather than take our word for it.

## Related

- [Messages](../guides/messages.md) — using them day to day.
- [Data & compliance](data-and-compliance.md) — ownership, residency, retention, and data requests.
- [How your data is kept separate](how-your-data-is-kept-separate.md) — how everything else is walled off.
