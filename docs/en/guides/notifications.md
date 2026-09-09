---
icon: lucide/bell
---

# Notifications

Initiative can tell you when something wants your attention — a task landed on you, somebody mentioned you, an event is creeping up.

What you get told about, and where, is entirely yours to decide. Nothing is being pushed into your inbox on your behalf for your own good.

## The three channels

| Channel | What it is |
|---|---|
| **Bell** | The in-app bell, and the notifications page behind it. |
| **Email** | Messages to your inbox. |
| **Mobile app** | Push notifications on your phone (needs the app, and permission). |

All three are yours, category by category, with no minimum — the bell included. Two categories keep the bell whatever you set: **Waiting on you** and **Your account**. Somebody's waiting on your decision, or somebody changed something about your account. Neither is a thing to discover in March. Their email and mobile switches turn off like anything else.

## The bell, and the page behind it

The **bell** holds everything you haven't read. Not the last twenty — the lot. The number says how many; opening it says what.

Everywhere else you get a **dot**: on the community in the left rail, then the initiative inside it, then the tool inside that. Follow it inward and you land on the thing, instead of opening five communities to work out which one was buzzing.

**See all**, at the foot of the bell, opens the full record — read and unread, grouped by day, filterable to unread, to mentions, or to one community. Anything in it can be marked read, marked unread again, or thrown away.

Two surfaces, two jobs. The bell is what's left to deal with. The page is what happened.

Notifications arrive **as they happen** — a mention lands the moment it's written. Reading one clears it on your other tabs too, so you don't dismiss the same thing three times on three devices.

!!! note "Click one and it stays put"
    It dims instead of vanishing, so the list doesn't reshuffle itself while you're still reading. It clears out when you close the bell.

## Choosing what you hear about

**User settings → Notifications** gives you a grid: one row per category, with a **Bell**, **Email** and **Mobile App** switch each.

| Category | You hear about it when… |
|---|---|
| **Mentions** | Somebody writes your name. |
| **Replies** | Somebody replies to something you said. |
| **Task assignments** | Somebody assigns you tasks (one summary, not one per task). |
| **Events** | You're invited to something, or something you're attending changes. |
| **Direct messages** | Somebody messaged you. You're told who and how many — never what it says, because nothing outside your own devices could tell you that. |
| **Comments on your work** | Somebody comments on a task you're on, or something you made. |
| **Reactions** | Somebody reacts to one of your comments (a summary). |
| **Overdue tasks** | A daily nudge about what's past due, at a time you choose. |
| **Event reminders** | Shortly before an event you're going to. |
| **Joining things** | You're added to an initiative, or a project appears in one. |
| **Waiting on you** | Somebody needs your decision — a join request, an access request. |
| **Posts** | A notice goes up on a board you can see. Only the people it was shared with hear about it. |
| **Connections** | Somebody asked to connect with you, or accepted. |
| **Exports and imports** | Something you asked for has finished. |
| **Your account** | Something was done to your account by somebody else. |

**Mentions** and **Comments on your work** are separate on purpose. Somebody typing your name is a decision about you. Somebody commenting on a task you happen to be on is just how busy the project got. Turn the second one down; keep the first.

![Notification settings](../images/notifications/settings.png)

## Per community

Every community you're in gets one dial.

| Setting | What reaches you |
|---|---|
| **Everything** | Whatever your categories allow. The default. |
| **Only what names me** | Mentions, replies, tasks assigned to you, event invitations, anything waiting on your decision, and your own exports. Nothing ambient. |
| **Nothing** | Nothing. |

**Nothing** is the real one, not a quieter one. That community will not reach you, and somebody typing your name there is not an exception — a mute you have to keep checking isn't a mute.

Three things ignore the dial, because they were never a community's to silence: **direct messages**, **connections**, and **your account**.

Most people set the dial and never open the grid again. If you do want one community to differ category by category, it's in there.

## Timing

A few of these are about *when*, not just *whether*:

- **Comments** on the same thing arrive as **one line**, however many there are. Twenty comments on a task you're on is one notification naming who commented and how many — not twenty. Once you've read it, the next comment starts a fresh one, so new activity is still news.
- **Task assignments** arrive as one summary once the dust has settled. Initiative waits until nothing new has landed on you for a few minutes, so somebody assigning you ten things reaches you as one message rather than ten separate ones — and sends anyway within half an hour if they're still going. Email and mobile follow the same schedule, so you're never told the same news twice at different times of day.
- **Reactions** work the same way, for the same reason: they arrive in flurries.
- **Overdue tasks** come as one **daily digest** at a time you pick, in your **timezone**.
- **Event reminders** are set per event — at the start, or a chosen number of minutes, hours or days before.

!!! tip "Set your timezone. Genuinely."
    Daily digests, quiet hours, due dates and repeating-task maths all run on your timezone. Initiative guesses it from your browser at sign-up and is usually right.

    But if your daily reminder is arriving at 4am, you have not been cursed and nothing is broken. Check **User settings → Interface**.

## Quiet hours

Set a window — 22:00 to 07:00, say — and email and mobile hold off inside it. The bell keeps collecting quietly; it was never going to wake you.

When the window ends you get **one** message per channel saying what happened, grouped by community:

```
While you were away
  Foundry — 3 mentions, 5 comments
  Acme    — 1 event invitation
```

One message, not a night of them replayed at seven in the morning. If nothing happened, nothing arrives.

## Turning on mobile push

1. Install the mobile app and sign in.
2. In **User settings → Notifications**, choose **Enable push notifications**.
3. Say yes when your phone asks.

If push shows as **Blocked**, that's your phone rather than us. Open your device settings, find Initiative, and let it talk to you. We can ask; your phone decides.

## Announcements

Notifications are about *your* work. An **announcement** is about the app itself: a version that changed something, a setting that moved, a maintenance window your administrator wants you to know about.

They arrive as a dialog rather than quietly in the bell, because they're the kind of thing genuinely worth stopping you for. Some are a single card; a longer one becomes a few pages you step through with **Next**. **Got it** clears it and it doesn't come back — unless whoever wrote it asked for more than one acknowledgement, in which case the dialog says so up front.

Dismissed one at speed and immediately regretted it? Nothing is lost. The **info icon in the sidebar footer** opens **Past announcements**: everything you've been shown, newest first, read and unread marked, with a filter for the ones you haven't read. Pictures open full size on a click.

Run a server and want to write one? See [Announcements](../admin/announcements.md).

## Related

- [Your space](your-space.md) — where your tasks and events gather.
- [Profile & preferences](../account/profile-and-preferences.md) — your timezone and everything else.
- [Announcements](../admin/announcements.md) — writing them, for administrators.
