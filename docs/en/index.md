---
icon: lucide/compass
---

# Welcome to Initiative

Initiative is a friendly home for your group's projects, tasks, documents, and plans. It's built for teams, clubs, gaming groups, and families who want to stay organized together without wrestling with complicated software.

!!! screenshot "The main screen, after signing in"
    **Show:** the whole app — the guild rail down the far left, the sidebar beside it (the guild's initiatives), and a project board open in the middle.

    When you have the picture, save it to `en/images/home/overview.png` and replace this box with:
    `![The Initiative home screen](images/home/overview.png)`

## New here? Start at the beginning

If this is your first time, **Getting started** is the place to go. It covers creating your account, finding your way around, and joining or creating your first workspace.

[Start with Getting started →](getting-started/index.md){ .md-button .md-button--primary }

## Find what you need

<div class="grid cards" markdown>

-   :material-rocket-launch-outline: __Getting started__

    Create an account, sign in, take the tour, and join your group.

    [:octicons-arrow-right-24: Getting started](getting-started/index.md)

-   :material-sitemap-outline: __How Initiative is organized__

    Guilds, initiatives, projects, documents — what they are and how they fit together.

    [:octicons-arrow-right-24: The big picture](concepts/index.md)

-   :material-book-open-variant: __Using Initiative__

    Day-to-day how-to guides for projects, tasks, documents, the calendar, and more.

    [:octicons-arrow-right-24: How-to guides](guides/index.md)

-   :material-account-multiple-check-outline: __Sharing & access__

    Decide who can see and edit each project and document.

    [:octicons-arrow-right-24: Sharing & access](sharing/index.md)

-   :material-shield-lock-outline: __Security & privacy__

    What "secure" means for you, and how your group's data stays separate from everyone else's.

    [:octicons-arrow-right-24: Security & privacy](security/index.md)

-   :material-cog-outline: __For administrators__

    Installing, configuring, and looking after your own Initiative server.

    [:octicons-arrow-right-24: Admin guide](admin/index.md)

</div>

??? techspec "For the technically minded — what Initiative is, briefly"
    Initiative is a self-hosted web application. The interface is a single-page web app; it talks to a Python service backed by a PostgreSQL database. Each group ("guild") gets its own isolated area of the database, and who-can-see-what is enforced inside the database itself, not only in the app. There's a companion mobile app (iOS and Android) for notifications and on-the-go use. More in [Security & privacy](security/index.md) and the [administrator guide](admin/index.md).

## A note on the words we use

Initiative borrows a few everyday words and gives them a specific meaning. The two you'll meet first:

- A **guild** is a workspace — one separate space for one group of people. Your book club and your work team would be two different guilds.
- An **initiative** is a folder for a big effort inside a guild. It gathers related projects and documents in one place.

There's a full [glossary](reference/glossary.md) if you ever hit a word you don't recognize.
