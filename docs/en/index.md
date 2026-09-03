---
icon: lucide/compass
---

# Welcome to Initiative

Initiative is where your group's projects, tasks, documents and plans live in one place. It's built for small businesses, clubs, committees, event teams, families, and anyone else coordinating work with other people — without having to learn project management first.

![The Initiative home screen](images/home/overview.png)

## Start small. It grows with you.

Day one, you get real value from one board with tasks on it. Later, when your group wants a shared calendar, or somewhere to write things down, or a way to see how the work is actually going — that's all waiting. Until then it stays out of your way.

[Start with Getting started →](getting-started/index.md){ .md-button .md-button--primary }

## Two ways to run it

Host it yourself — it's open source, free, and the complete product. Or, soon, let us host it for you as a paid service and never think about a database again. Same software either way; we're not keeping the good parts back. [Which one is you? →](self-host-or-hosted.md)

## Find what you need

<div class="grid cards" markdown>

-   :material-rocket-launch-outline: __Getting started__

    Make an account, sign in, take the tour, join your group.

    [:octicons-arrow-right-24: Getting started](getting-started/index.md)

-   :material-sitemap-outline: __How Initiative is organized__

    Communities, initiatives, projects, documents — what they are and how they nest.

    [:octicons-arrow-right-24: The big picture](concepts/index.md)

-   :material-book-open-variant: __Using Initiative__

    How-to guides for projects, tasks, documents, the calendar, and the rest.

    [:octicons-arrow-right-24: How-to guides](guides/index.md)

-   :material-storefront-outline: __Apps & the marketplace__

    Ready-made dashboards and apps, built by groups like yours.

    [:octicons-arrow-right-24: Apps & the marketplace](guides/apps-and-marketplace.md)

-   :material-account-multiple-check-outline: __Sharing & access__

    Decide exactly who sees and edits each project and document.

    [:octicons-arrow-right-24: Sharing & access](sharing/index.md)

-   :material-shield-lock-outline: __Security & privacy__

    What "secure" means for you, and how your group's data stays yours.

    [:octicons-arrow-right-24: Security & privacy](security/index.md)

-   :material-cog-outline: __For administrators__

    Installing, configuring, and looking after your own server.

    [:octicons-arrow-right-24: Admin guide](admin/index.md)

-   :material-help-circle-outline: __FAQ__

    Quick answers to what people ask most.

    [:octicons-arrow-right-24: FAQ](faq.md)

</div>

## You choose who sees what

Nothing here is visible to "everyone" by default. Your group's space is separate from every other group's. Inside it, each effort is visible only to the people you add to it. And individual projects and documents narrow further still.

Which means a business owner keeps payroll planning away from the seasonal staff, and an event team plans next year's programme without the volunteers reading along — same workspace, no extra setup. [How that works →](sharing/index.md)

## The tools come from people like you

Whatever your group needs, some other group with the same problem has usually already built it. The **marketplace** lets you add ready-made dashboards and apps in a couple of clicks — no developer, no custom build, no waiting for us to ship a feature.

It's curated rather than a free-for-all: your marketplace holds what ships with Initiative plus what the person running your server has approved. See [Apps & the marketplace](guides/apps-and-marketplace.md).

## Why we built this

We're self-hosters. We got here the way most people do — by growing steadily less comfortable with what the tools we relied on were doing with the things we put into them.

What tipped it was watching creative work get swallowed into training data by companies that never thought to ask. AI is genuinely useful and we're not here to shake a fist at it. But being useful doesn't grant anyone the right to take what somebody made and feed it to a machine. Once that's happened to something you made, "we promise not to" stops sounding like much of a promise.

So we treat this as an architecture problem rather than a policy one. A policy is only as durable as whoever owns the company next. A system with no path to your content doesn't depend on anyone's good intentions. That's the thinking behind the parts of Initiative that look strict — no standing admin access to a community's data, cross-community access only through a time-bound grant that leaves a record, and private messages encrypted so thoroughly that no key to them exists outside the two devices talking.

The upshot: **we can't feed your work to a model, because there's no pipe to put it in.** The AI features we do have are ones you point at your own content on purpose, with a key you or your administrator supplied, and they send only what you asked for — under that provider's terms, which we'll tell you to read rather than pretend we control. See [AI features](account/ai-features.md).

We'd rather build something we're comfortable keeping our own work in.

## A note on the words we use

Initiative borrows a couple of everyday words and gives them specific jobs. The two you'll meet first:

- A **community** is a workspace — one separate space for one group of people. Your book club and your work team would be two different communities.
- An **initiative** is a folder for a big effort inside a community, gathering its projects and documents in one place.

The [glossary](reference/glossary.md) has the rest, for whenever a word ambushes you.

??? techspec "For the technically minded — what this actually is"
    Initiative is a web application you can run yourself. The interface is a single-page web app talking to a Python service backed by PostgreSQL. Each community gets its **own database schema**, so a request in one community cannot address another community's tables at all; the finer layers inside a community — which effort, which role, which item — are enforced by the database's own row-level security rather than by application code. There's a companion mobile app for iOS and Android. More in [Security & privacy](security/index.md) and the [administrator guide](admin/index.md).

## Built in the open

Initiative is developed publicly, and what the people using it say shapes what gets built next. If something here is unclear, wrong, or missing, tell us — [the project on GitHub](https://github.com/Morelitea/initiative) is where that happens.
