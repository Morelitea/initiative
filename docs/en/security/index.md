---
icon: lucide/shield-check
---

# Security & privacy

"Is my stuff safe and private?" is a fair question to ask of anything you hand your group's information to.

Short answer: the only people who see something are the people you deliberately gave it to. That isn't a setting to hunt for and switch on — it's how the layers work by default, all the way down to the database. Here's what that means day to day, and where the detail lives.

- **This page** explains what security means for *you*, as someone using Initiative day to day.
- **[How your data is kept separate](how-your-data-is-kept-separate.md)** is the technical explanation of multi-tenancy and how the boundaries are enforced — written for project managers, administrators, and anyone evaluating Initiative.
- **[Private messages](private-messages.md)** explains what end-to-end encryption covers, and what could and could not be handed over if somebody asked.
- **[Data & compliance](data-and-compliance.md)** covers data ownership, encryption, your data rights, and what compliance posture you can expect.
- **[Reporting a problem](reporting-a-problem.md)** is how to responsibly report a security concern.

## What "secure" means for you

In everyday terms, Initiative is built so that:

### Your group's data is separate from every other group's

Each community is a sealed space. Another group using the same Initiative server cannot see your projects, documents, or tasks — and you can't see theirs. This separation isn't a setting that could be toggled off by accident: every community's content lives in its own dedicated area of the database (a separate *schema*), created with the community and removed with it. The finer layers — which effort, which role, which item — are enforced inside that space by the database as well (more in the technical pages).

### Sensitive work stays with the people involved

Inside a community, an **initiative** is only visible to its members. So a small group can work on something private without the rest of the community seeing it — a business's finances away from its seasonal staff, a hiring committee's notes away from the rest of the team. And individual projects and documents can be narrowed further still — see [Sharing & access](../sharing/index.md).

This is the layer most groups rely on day to day, and it needs no configuration: someone who isn't in an initiative simply doesn't have it.

### Your sign-in is protected

- Your sign-in session is held in a cookie the page's own scripts can't read.
- You can use your organization's **single sign-on** instead of a separate password.
- Passwords must be **at least 12 characters**, and are never stored in readable form.

### Sensitive information is encrypted

The most sensitive stored fields — saved API keys, email addresses, and the like — are **encrypted at rest**, so the raw database file doesn't carry them in the clear. More in [Data & compliance](data-and-compliance.md).

### Your private messages are only yours

Direct messages are **end-to-end encrypted**: written on your device, read on theirs, and unreadable everywhere in between. A community admin can't read them, whoever runs the server can't read them, and neither can we — not as a policy, but because no key to them exists outside the two devices talking.

The trade is that your history lives on your devices rather than on a server, so a new device starts from when it arrived and signing out takes that device's copy with it. See [Private messages](private-messages.md).

### You stay in control of your account

- See **where you're signed in** and sign out any device you don't recognize, from **User settings → Security**.
- Create and **revoke access keys** for apps and scripts at any time (see [API keys & integrations](../account/api-keys-and-integrations.md)).
- **Deactivate or delete your account** whenever you choose, from **User settings → Danger Zone**. You decide whether your content is preserved or removed. See [Data & compliance](data-and-compliance.md).

## A few habits that do most of the work

Security is a partnership, and your half of it is genuinely not complicated:

- **Use a strong, unique password** (or single sign-on). A password manager makes this effortless.
- **Sign out on shared computers**, and don't tick "stay signed in" on a device that isn't yours.
- **Share at the lowest level that works** — Viewer rather than Editor, a few people rather than everyone — and widen later if needed.
- **Be careful with access keys.** Treat an API key like a password; if one might be exposed, delete it.
- **Tell someone if something looks wrong.** If you can see something you don't think you should, that's worth reporting — see [Reporting a problem](reporting-a-problem.md).

## For administrators

If you run the server, security also depends on how you set it up and look after it — strong secrets, backups, updates, and sensible configuration. That's covered in the [administrator guide](../admin/index.md), especially [Configuration](../admin/configuration.md) and [Backups & updates](../admin/backups-and-updates.md).
