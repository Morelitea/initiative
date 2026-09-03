---
icon: lucide/compass
---

# Welcome to Initiative

Initiative is where your group's projects, tasks, documents and plans all live in one place.

Right now they're probably living across a group chat, two spreadsheets, an email thread from March, and the head of whoever's been doing this the longest. We know about the spreadsheet. We know about the merged cells. It's fine. We're here now.

![The Initiative home screen](images/home/overview.png)

## Start small. No, smaller than that.

Day one: make one board, put a few tasks on it. Done. That's a complete setup — a real, working system — and if you never touch another feature you will still be dramatically better off than you were on Tuesday.

Everything else is already installed and waiting. Documents, a calendar, dashboards, the lot. None of it will bother you until you go looking for it. It has nowhere else to be.

[Start with Getting started →](getting-started/index.md){ .md-button .md-button--primary }

## You cannot break this

This is the thing people actually worry about, so let's clear it up first.

- **Deleted something?** It's in the Trash. Go and get it.
- **Moved a task somewhere daft?** Move it back. Nobody saw.
- **Made an initiative you didn't need?** Archive it and it leaves your life entirely.
- **Made a project called "test"?** Yeah. Everyone does. It's still there, isn't it.

There's exactly one genuinely permanent button in the whole app, and it makes you type things out to prove you meant it. Everything else survives being dropped down the stairs. Click around — you're not going to hurt it.

## Two ways to run it

**Host it yourself** — open source, free, the entire product, running on whatever machine you've got going spare.

**Or let us host it** (soon) — pay us and never think about a database again, which is an extremely reasonable thing to want and possibly the correct answer for most people.

Same software either way. We're not keeping the good bits back for the paying customers. [Which one is you? →](self-host-or-hosted.md)

## Find what you need

<div class="grid cards" markdown>

-   :material-rocket-launch-outline: __Getting started__

    Make an account, find your way around, join your group.

    [:octicons-arrow-right-24: Getting started](getting-started/index.md)

-   :material-sitemap-outline: __How Initiative is organized__

    Communities, initiatives, projects, documents — what they are and how they fit together.

    [:octicons-arrow-right-24: The big picture](concepts/index.md)

-   :material-book-open-variant: __Using Initiative__

    How-to guides for projects, tasks, documents, the calendar and everything else.

    [:octicons-arrow-right-24: How-to guides](guides/index.md)

-   :material-storefront-outline: __Apps & the marketplace__

    Ready-made dashboards and apps, built by groups like yours.

    [:octicons-arrow-right-24: Apps & the marketplace](guides/apps-and-marketplace.md)

-   :material-account-multiple-check-outline: __Sharing & access__

    Decide exactly who sees and edits each project and document.

    [:octicons-arrow-right-24: Sharing & access](sharing/index.md)

-   :material-shield-lock-outline: __Security & privacy__

    What "secure" means for you, and how your group's stuff stays yours.

    [:octicons-arrow-right-24: Security & privacy](security/index.md)

-   :material-cog-outline: __For administrators__

    Installing, configuring, and looking after your own server.

    [:octicons-arrow-right-24: Admin guide](admin/index.md)

-   :material-help-circle-outline: __FAQ__

    Quick answers to the things people ask most.

    [:octicons-arrow-right-24: FAQ](faq.md)

</div>

## You choose who sees what

Nothing here is visible to "everyone" by default, and there is no buried setting you have to find and switch on to make that true.

Your group's space is separate from every other group's. Inside it, each effort is only visible to the people you actually put in it. And any individual project or document can be narrowed down further than that.

Which is how the payroll planning stays away from the seasonal staff, and next year's programme stays away from this year's volunteers, in the same workspace, with nothing configured, and nobody wandering into a folder they were never meant to see. [How that works →](sharing/index.md)

## The tools come from people like you

Whatever your group needs, some other group with the exact same problem has almost certainly already built it, got fed up rebuilding it by hand every year, and shared it.

That's the **marketplace**: ready-made dashboards and apps you add in about two clicks. No developer. No custom build. No waiting for us to get round to it.

It's curated rather than open season — your marketplace holds what ships with Initiative plus whatever the person running your server has approved. See [Apps & the marketplace](guides/apps-and-marketplace.md).

## Why we built this

We're self-hosters. We got here the way most people do: by slowly going off the tools we relied on, as it became clearer what they were doing with the things we put into them.

What tipped it was watching creative work get hoovered into training data by companies that never thought to ask. To be clear, we like AI. We use it. But being useful doesn't entitle anyone to take what somebody made and feed it to a machine — and once that's happened to something of yours, "we promise not to" stops sounding like much of a promise.

So we treated it as an architecture problem rather than a policy one. A policy lasts exactly as long as the person who wrote it stays in charge. A system with no path to your content doesn't need anybody to stay good.

That's why bits of Initiative are stricter than they strictly need to be. Nobody holds standing admin access to a community's data. Reaching into another community takes a time-limited grant that leaves a record. Direct messages are encrypted well enough that no key to them exists outside the two phones talking. We locked ourselves out on purpose, and we'd do it again.

Which means: **we can't feed your work to a model, because there's no pipe to put it in.** The AI features that do exist are ones you point at your own stuff deliberately, using a key you or your admin supplied, and they send only what you asked them to — under that provider's terms, which we'll tell you to go and read rather than pretend we control. See [AI features](account/ai-features.md).

Mostly we wanted somewhere we'd be happy keeping our own work.

## A note on the words we use

Initiative takes two perfectly ordinary words and gives them specific jobs. Sorry.

- A **community** is a workspace — one separate space for one group of people. Your book club and your work team are two different communities.
- An **initiative** is a folder for a big effort inside a community. It holds that effort's projects and documents.

And yes, the app is also called Initiative. We know. We've made our peace with it, and so will you. The [glossary](reference/glossary.md) has every other word we've borrowed.

??? techspec "For the technically minded — what this actually is"
    Initiative is a web application you can run yourself. A single-page web app talking to a Python service backed by PostgreSQL. Each community gets its **own database schema**, so a request in one community cannot address another community's tables at all; the finer layers inside a community — which effort, which role, which item — are enforced by the database's own row-level security rather than by application code. There's a companion mobile app for iOS and Android. More in [Security & privacy](security/index.md) and the [administrator guide](admin/index.md).

## Built in the open

Initiative is developed in public, and what people using it say genuinely shapes what gets built next.

So if something here is unclear, wrong, or conspicuously missing, tell us. [The project's on GitHub](https://github.com/Morelitea/initiative), and we do actually read it.
