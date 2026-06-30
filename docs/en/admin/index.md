---
icon: lucide/server-cog
---

# For administrators

This section is for the person who **runs** Initiative for their group — installing it, configuring it, and keeping it healthy. It's more technical than the rest of the help center by nature, but we've kept it as plain as the subject allows.

If you only *use* Initiative, you can happily skip this section. Everything you need is in [Using Initiative](../guides/index.md).

!!! info "You don't need to be a server expert"
    The recommended setup uses Docker Compose, which is mostly copy-a-file-and-edit-a-few-values. If you can follow a recipe and edit a text file, you can run Initiative. The deeper topics are here when you need them.

## What's in this section

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

    Set up outgoing email for invites and reminders.

    [:octicons-arrow-right-24: Email](email.md)

-   :material-cellphone-message: __Push notifications__

    Enable mobile push via Firebase.

    [:octicons-arrow-right-24: Push notifications](push-notifications.md)

-   :material-database-outline: __File & object storage__

    Keep uploads on disk, or use S3-compatible storage.

    [:octicons-arrow-right-24: Object storage](object-storage.md)

-   :material-shield-crown-outline: __Platform roles__

    Server-wide roles, capabilities, and break-glass access.

    [:octicons-arrow-right-24: Platform roles](platform-roles.md)

-   :material-backup-restore: __Backups & updates__

    Protect your data and stay current.

    [:octicons-arrow-right-24: Backups & updates](backups-and-updates.md)

-   :material-book-edit-outline: __Maintaining these docs__

    Build, preview, and publish this help center.

    [:octicons-arrow-right-24: Maintaining these docs](maintaining-these-docs.md)

</div>

## The first thing to know

The **first person to register** on a fresh Initiative server automatically becomes the **owner** — the top administrator, the only role that can change server-wide settings. So the very first sign-up should be you (or whoever will run the server). See [Platform roles](platform-roles.md).
