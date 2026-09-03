---
icon: lucide/bell
---

# Notifications

Initiative tells you when something wants your attention — a task assigned, a mention, an event coming up. What you're told about and where is entirely yours.

## The three channels

| Channel | What it is |
|---|---|
| **Bell** | The in-app bell. Always shows your notifications, whatever else you've set. |
| **Email** | Messages to your inbox. |
| **Mobile app** | Push notifications on your phone (needs the app, and permission). |

The **bell** is always on. **Email** and **mobile** are yours to switch, per category.

Bell notifications arrive **as they happen** — a mention lands the moment it's written, not whenever the page next thinks to check. Marking one read updates your other open tabs too, so you don't clear the same thing twice.

## Choosing what you hear about

**User settings → Notifications** gives you a grid: one row per category, with an **Email** and a **Mobile App** toggle each.

| Category | You're notified when… |
|---|---|
| **Initiative invites** | You're added to a new initiative. |
| **Task assignments** | Someone assigns you tasks (one summary, not one-by-one). |
| **Mentions** | Someone `@mentions` you or comments on your work. |
| **Reactions** | Someone reacts to one of your comments (also a summary). |
| **New project in initiative** | A project is created in one of your initiatives. |
| **Overdue tasks** | A daily reminder of what's past due, at a time you pick. |
| **Events** | You're invited to an event, or one you're attending changes. |
| **Event reminders** | Shortly before an event you're attending. |
| **Direct messages** | Somebody messaged you. You're told who and how many — never what it says, because nothing outside your own devices could. |

![Notification settings](../images/notifications/settings.png)

## Timing

A few categories are about *when*, not just *whether*:

- **Task assignments** arrive as one summary once the dust settles. Initiative waits until nothing new has been assigned to you for a few minutes, so a batch reaches you as a single message rather than a stream — and sends anyway within half an hour if they keep coming. Email and mobile follow the same schedule, so you never get the same news twice at different times.
- **Reactions** work the same way, for the same reason: they arrive in flurries. The bell shows each as it happens; email and mobile wait and summarize.
- **Overdue tasks** arrive as one **daily digest** at a time you set, in your **timezone**.
- **Event reminders** are set per event — at the start, or a chosen number of minutes, hours or days before.

!!! tip "Set your timezone"
    Daily digests, due dates and recurring-task math all run on your timezone. Initiative guesses it from your browser at sign-up; if that's wrong, fix it in **User settings → Interface**.

## Turning on mobile push

1. Install the mobile app and sign in.
2. In **User settings → Notifications**, choose **Enable push notifications**.
3. Allow notifications when your phone asks.

If push shows as **Blocked**, your phone is blocking the app — open your device settings, find Initiative, and allow notifications there.

## Announcements

Notifications are about *your* work. An **announcement** is about the app itself: a version that changed something, a setting that moved, a maintenance window your administrator wants you to plan around.

They arrive as a dialog rather than in the bell, because they're the kind of thing worth being stopped for. Some are a single card; one with more to say becomes a few pages you step through with **Next**. **Got it** clears it and it doesn't come back — unless whoever wrote it asked for more than one acknowledgement, in which case the dialog says so.

Dismissed one in a hurry? Nothing's lost. The **info icon in the sidebar footer** opens **Past announcements**: everything you've been shown, newest first, read and unread marked, with a filter for the unread ones. Pictures open full size on a click.

Run a server and want to write one? See [Announcements](../admin/announcements.md).

## Related

- [Your space](your-space.md) — where your tasks and events gather.
- [Profile & preferences](../account/profile-and-preferences.md) — your timezone and other settings.
- [Announcements](../admin/announcements.md) — writing them, for administrators.
