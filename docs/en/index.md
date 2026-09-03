---
icon: lucide/compass
---

# Welcome to Initiative

Initiative is where your group's projects, tasks, documents and plans all live in one place.

Right now they're living across a group chat, two spreadsheets, an email thread from March, and the head of whoever's been doing this the longest.

We know about the spreadsheet. We know about the merged cells. We know somebody colour-coded it in 2019 and nobody now remembers what green means. It's fine. We're here now.

![The Initiative home screen](images/home/overview.png)

## Start small. No, smaller than that.

Day one: make one board, put a few tasks on it. Done. That's a complete setup — a real, functioning system — and if you never touch another feature you'll still be dramatically better off than you were on Tuesday.

Everything else is already installed and waiting. Documents, a calendar, dashboards, the lot. None of it will bother you, email you, or pop up to ask whether you've considered optimising your workflow. It has nowhere else to be.

[Start with Getting started →](getting-started/index.md){ .md-button .md-button--primary }

## You cannot break this

This is the thing people actually worry about, so let's clear it up first.

- **Deleted something?** It's in the Trash, sulking. Go and get it.
- **Moved a task somewhere daft?** Move it back. Nobody saw.
- **Made an initiative you didn't need?** Archive it. It leaves your life entirely and does not write.
- **Made a project called "test"?** Everyone does. It's still there, isn't it.
- **Made *four* projects called "test"?** Also fine. Marginally funnier. Still fine.

There is exactly one genuinely permanent button in this entire application, and it makes you type things out longhand to prove you meant it. Everything else survives being dropped down the stairs.

So click things. Open menus. Drag stuff about. The worst outcome available to you today is a mildly untidy sidebar.

## We say no to things

Initiative is meant to help you, not to gradually become the tool with so many features that operating it is its own part-time job.

So some things are left out on purpose. There are no group chats, for instance — because everything here already has **comments** on it, and they're searchable. The conversation about a thing sits on that thing, where the next person finds it without being told where to look.

Whereas a group chat is where somebody pastes the thing that should have been a document, and six months later everyone is scrolling for it, and Jenny has left, and somebody is looking at the printer in a way the printer has done nothing to deserve.

## Two ways to run it

**Host it yourself** — open source, free, the entire product, running on whatever machine you've got going spare. A ten-year-old laptop with a broken hinge is a perfectly respectable server.

**Or let us host it** (soon) — pay us and never think about a database again, which is an extremely reasonable thing to want and quietly the correct answer for most people.

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

Nothing here is visible to "everyone" by default, and there's no buried setting you have to find to make that true. Your group's space is separate from every other group's; inside it, each effort is only visible to the people you put in it; and any project or document narrows down further still.

Which is how the payroll planning stays away from the seasonal staff, and next year's programme away from this year's volunteers — same workspace, nothing configured, nobody wandering into a folder they were never meant to see. [How that works →](sharing/index.md)

## The tools come from people like you

Whatever your group needs, some other group has needed precisely the same thing, built it, spent three years rebuilding it by hand every January, finally snapped, and shared it.

That's the **marketplace**: ready-made dashboards and apps, about two clicks each. It's curated rather than open season — yours holds what ships with Initiative plus whatever the person running your server approved. See [Apps & the marketplace](guides/apps-and-marketplace.md).

## Why we built this

We're self-hosters. We got here the way most people do: by slowly going off the tools we relied on, as it became clearer what they were doing with the things we put into them.

What tipped it was watching creative work get hoovered into training data by companies that never thought to ask. To be clear, we like AI. We use it. But being useful doesn't entitle anyone to take what somebody made and feed it to a machine — and once that's happened to something of yours, "we promise not to" stops sounding like much of a promise.

So we treated it as an architecture problem rather than a policy one, because a policy lasts exactly as long as the person who wrote it stays in charge. Nobody holds standing admin access to a community's data. Reaching into another community takes a time-limited grant that leaves a record. Direct messages are encrypted well enough that no key to them exists outside the two phones talking. We locked ourselves out on purpose, and we'd do it again.

Which means **we can't feed your work to a model, because there's no pipe to put it in.** The AI features that do exist are ones you point at your own stuff deliberately, and they send only what you asked — under that provider's terms, which we'll tell you to go and read rather than pretend we control. See [AI features](account/ai-features.md).

## A note on the words we use

Initiative takes two perfectly ordinary words and gives them specific jobs. Sorry.

- A **community** is a workspace — one separate space for one group of people. Your book club and your work team are two different communities.
- An **initiative** is a folder for a big effort inside a community.

And yes, the app is also called Initiative. We know. The [glossary](reference/glossary.md) has every other word we've borrowed.

??? techspec "For the technically minded — what this actually is"
    Initiative is a web application you can run yourself. A single-page web app talking to a Python service backed by PostgreSQL. Each community gets its **own database schema**, so a request in one community cannot address another community's tables at all; the finer layers inside a community — which effort, which role, which item — are enforced by the database's own row-level security rather than by application code. There's a companion mobile app for iOS and Android. More in [Security & privacy](security/index.md) and the [administrator guide](admin/index.md).

## Built in the open

Initiative is developed in public, and what people using it say genuinely shapes what gets built next. So if something here is unclear, wrong, or conspicuously missing, tell us — [the project's on GitHub](https://github.com/Morelitea/initiative), and we do actually read it.
