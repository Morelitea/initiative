---
icon: lucide/server-cog
---

# For administrators

This section is for whoever **runs** Initiative for their group — installing it, configuring it, keeping it healthy.

If you only *use* Initiative, skip all of this. Everything you need is in [Using Initiative](../guides/index.md).

!!! info "You don't need to be a server expert"
    The recommended setup is Docker Compose, which is mostly copy-a-file-and-edit-a-few-values. If you can follow a recipe and edit a text file, you can run Initiative. The deeper topics are here for when you want them, not before.

Not sure you want to run a server at all? A paid hosted service is on the way — see [Self-host or let us host it](../self-host-or-hosted.md).

## What's in here

<div class="grid cards" markdown>

-   :material-download-box-outline: __Installation__

    Get Initiative running with Docker Compose.

    [:octicons-arrow-right-24: Installation](installation.md)

-   :material-tune: __Configuration__

    The settings that control how your server behaves.

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-account-key-outline: __Single sign-on__

    Connect your identity provider (OIDC).

    [:octicons-arrow-right-24: Single sign-on](single-sign-on.md)

-   :material-email-outline: __Email__

    Outgoing mail for invites and reminders.

    [:octicons-arrow-right-24: Email](email.md)

-   :material-cellphone-message: __Push notifications__

    Mobile push via Firebase.

    [:octicons-arrow-right-24: Push notifications](push-notifications.md)

-   :material-database-outline: __File & object storage__

    Keep uploads on disk, or move them to S3.

    [:octicons-arrow-right-24: Object storage](object-storage.md)

-   :material-package-variant-plus: __Publishing your own listings__

    Add your own dashboards and apps to the marketplace.

    [:octicons-arrow-right-24: Publishing listings](publishing-listings.md)

-   :material-shield-crown-outline: __Platform roles__

    Server-wide roles, capabilities, and break-glass access.

    [:octicons-arrow-right-24: Platform roles](platform-roles.md)

-   :material-bullhorn-outline: __Announcements__

    Tell everyone on your server something they have to act on.

    [:octicons-arrow-right-24: Announcements](announcements.md)

-   :material-backup-restore: __Backups & updates__

    Protect your data and stay current.

    [:octicons-arrow-right-24: Backups & updates](backups-and-updates.md)

-   :material-book-edit-outline: __Maintaining these docs__

    Build, preview, and publish this help center.

    [:octicons-arrow-right-24: Maintaining these docs](maintaining-these-docs.md)

</div>

## The first thing to know

The **first person to register** on a fresh server automatically becomes the **owner** — the top administrator, and the only role that can change server-wide settings. So make sure the very first sign-up is you, or whoever's actually going to run this. See [Platform roles](platform-roles.md).
