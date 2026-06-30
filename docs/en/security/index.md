---
icon: lucide/shield-check
---

# Security & privacy

"Is my stuff safe and private?" is a fair question to ask of any tool you trust with your group's information. This section answers it twice: once in plain language for everyone, and once in technical detail for the people who want it.

- **This page** explains what security means for *you*, as someone using Initiative day to day.
- **[How your data is kept separate](how-your-data-is-kept-separate.md)** is the technical explanation of multi-tenancy and how the boundaries are enforced — written for project managers, administrators, and anyone evaluating Initiative.
- **[Data & compliance](data-and-compliance.md)** covers data ownership, encryption, your data rights, and what compliance posture you can expect.
- **[Reporting a problem](reporting-a-problem.md)** is how to responsibly report a security concern.

## What "secure" means for you

In everyday terms, Initiative is built so that:

### Your group's data is separate from every other group's

Each guild is a sealed space. Another group using the same Initiative server cannot see your projects, documents, or tasks — and you can't see theirs. This separation isn't just a setting that could be toggled off by accident; it's built into the foundations (more in the technical pages).

### Sensitive work stays with the people involved

Inside a guild, an **initiative** is only visible to its members. So a small group can work on something private without the rest of the guild seeing it. And individual projects and documents can be narrowed further still — see [Sharing & access](../sharing/index.md).

### Your sign-in is protected

- Signing in uses a secure session that **can't be stolen by malicious scripts** in your browser — a common way accounts get hijacked elsewhere, closed off here.
- You can use your organization's **single sign-on** instead of a separate password.
- Passwords must be **at least 12 characters**, and they're never stored in a readable form.

### Sensitive information is encrypted

Behind the scenes, the most sensitive pieces of stored data — things like saved API keys and email addresses — are **encrypted at rest**, so they're not readable even to someone who somehow got hold of the raw database files. More in [Data & compliance](data-and-compliance.md).

### You stay in control of your account

- See **where you're signed in** and sign out any device you don't recognize, from **User settings → Security**.
- Create and **revoke access keys** for apps and scripts at any time (see [API keys & integrations](../account/api-keys-and-integrations.md)).
- **Deactivate or delete your account** whenever you choose, from **User settings → Danger Zone**. You decide whether your content is preserved or removed. See [Data & compliance](data-and-compliance.md).

## Simple habits that keep you safe

Security is a partnership. A few small habits go a long way:

- **Use a strong, unique password** (or single sign-on). A password manager makes this effortless.
- **Sign out on shared computers**, and don't tick "stay signed in" on a device that isn't yours.
- **Share at the lowest level that works** — Viewer rather than Editor, a few people rather than everyone — and widen later if needed.
- **Be careful with access keys.** Treat an API key like a password; if one might be exposed, delete it.
- **Tell someone if something looks wrong.** If you can see something you don't think you should, that's worth reporting — see [Reporting a problem](reporting-a-problem.md).

## For administrators

If you run the server, security also depends on how you set it up and look after it — strong secrets, backups, updates, and sensible configuration. That's covered in the [administrator guide](../admin/index.md), especially [Configuration](../admin/configuration.md) and [Backups & updates](../admin/backups-and-updates.md).
