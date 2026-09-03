---
icon: lucide/scale
---

# Data & compliance

This page explains who owns your data, where it lives, the rights you have over it, and — honestly — what compliance posture you can and can't expect. It's written for the people who have to answer these questions for their organization, but the first part is for everyone.

## Two ways to run Initiative

Initiative is one product you can get in two ways, and the difference shows up mostly in who does the operational work:

- **You host it yourself.** Initiative is open source and runs on hardware your group controls, or a host your group chooses. Everything below is true of it — you just hold the machine as well.
- **We host it for you** *(coming soon)*. You sign up and start; keeping the service running, backed up, and up to date is ours to do.

Both are the same software, with the same protections — nothing is held back from the version you run yourself. Where a section below depends on which you chose, it says so.

## Who owns what

The rule is a simple one: **communities own community data, and people own their own.** In practice that means:

- **A community's content belongs to the community.** Its projects, tasks, documents, and files are the group's, and its admins act for the group — they decide who may see what, what gets exported, and what gets deleted. Writing a task doesn't make it privately yours any more than minuting a meeting makes the minutes yours.
- **Your account is yours.** Your profile, your picture, your preferences, your handle and email address — yours across every community you're in, and yours to take with you or delete.
- **Your messages are yours and the other person's**, and nobody else's. Not the community's, not an admin's, not ours. See [Private messages](private-messages.md).

None of it is ours. We don't sell it, we don't mine it, and it isn't training data.

If you host Initiative yourself, all of it sits in *your* database and *your* file storage, and backing it up is your job too. See [Backups & updates](../admin/backups-and-updates.md).

If we host it, we hold it **on behalf of the people it belongs to**, and the tools stay in their hands: export it whenever you like, delete it whenever you like, take it elsewhere. The export formats below are ordinary files, not something only we can open.

## Why we built it this way

A word on where this comes from, because it explains choices that might otherwise look severe.

We're self-hosters. We got there the way most people do — by growing steadily less comfortable with what the tools we relied on were doing with the things we put into them. What tipped it for us was watching creative work get swallowed into training data by companies that never thought to ask. Once that has happened to something you made, "we promise not to" stops sounding like much of a promise.

So we treat this as an architecture problem rather than a policy one. A policy is only as durable as whoever owns the company next; a system with no path to your content doesn't depend on anybody's good intentions. That's the thinking behind the parts of Initiative that can feel strict: no standing administrative access to a community's data, cross-community access only through a time-bound grant that leaves a record, and private messages encrypted so thoroughly that no key to them exists outside the two devices talking.

The practical upshot is that **we can't feed your work to a model** — there's no pipe to put it in. The AI features that do exist are ones you point at your own content deliberately, with a key you or your administrator supplied, and they send only what you asked them to. See [AI features](../account/ai-features.md).

We'd rather build something we're comfortable keeping our own work in.

## Where your data lives (data residency)

If you host Initiative yourself, your data lives wherever your server runs. If that's a computer in your office, your data is in your office; if it's a cloud server in a particular country, your data is in that country. **You choose** — which makes meeting data-residency requirements a matter of where you deploy, not something to negotiate with a vendor.

If we host it, your data lives where our service runs. For a group with a residency requirement it can't meet, self-hosting is always there — it's the same software, and there is no feature held back from it.

## How your data is protected

- **In transit:** traffic between browsers and the server is encrypted over HTTPS.
- **At rest:** the most sensitive stored fields — saved AI keys, single-sign-on secrets, email-server passwords, and email addresses — are encrypted in the database.
- **End-to-end, for direct messages:** private messages are encrypted on the sending device and decrypted on the receiving one. Nobody in between can read them, including us and including an administrator of the server they passed through. See [Private messages](private-messages.md).
- **Access control:** everything else is gated by the [six-layer model](how-your-data-is-kept-separate.md) and enforced in the database.

## Your data rights

### Getting your data out

Initiative is built to avoid locking your information in:

- **Export a project** to a portable file you can keep or re-import elsewhere.
- **Export spreadsheets** as CSV or Excel (XLSX).
- **Export calendar events** as standard `.ics` files.
- Administrators can **export the user list** as CSV.

### Removing data

- **Anything you delete** goes to the **Trash** first, where it can be restored until the retention period passes — then it's permanently removed. Administrators set how long that is (see [Working with communities](../guides/communities.md#trash-and-retention)).
- **Your account** can be **deactivated** (you can't sign in, but your content stays) or **deleted**. Deleting offers a choice: *anonymize* (your personal details are removed and your past contributions show as "Deleted user") or, for administrators, *hard delete* (everything is removed). See [Profile & preferences](../account/profile-and-preferences.md).

Together, the **export** tools above and these **removal** tools cover the two requests privacy laws ask for most often: handing someone a copy of the data held about them (a *right to access* request), and erasing their personal information (a *right to erasure* request).

### Accountability

Sensitive cross-group access is **recorded**. When an administrator or support person uses an emergency "break-glass" grant, or a time-bound access request is approved, that event is logged with who, which community, and why — so privileged access is auditable rather than invisible.

### Age, and what we ask for

Communities that list themselves in the community directory can be found by anyone signed in, which means they are open to people you have not met. Taking a place in one asks your date of birth, once.

**The date is not kept.** It is used to work out whether you are old enough and then discarded. Your account records that you answered and when — never the date itself. There is no field for it, nothing logs it, and it is not sold or shared with anyone.

Only the parts of Initiative that are open to people outside your own communities ask at all. A private community — one that has not listed itself — never does, and neither does an invite into one.

If you answer that you are not old enough, that answer is kept — again, the fact and not the date — and you are not asked again. Somebody on the support tier or above can reset the question for you, which is the way back from a mistyped year. Resetting it is recorded in the audit log, like every other action one person takes on another's account.

Administrators of a deployment where every account is known to belong to an adult can switch the question off entirely, under **Settings › Admin › Community**.

## What could be handed over

A question worth answering before you have to ask it: if somebody with legal authority demanded your group's data, what exists to give them?

**On a server you run**, the answer is between you and them — nobody else holds a copy to be asked for.

**On a server we run**, we answer lawful requests, and what we can produce is limited to what actually exists:

| Asked for | What exists |
|---|---|
| Projects, tasks, documents, files | Held on your behalf, and readable. This is your working data. |
| The content of direct messages | **Nothing.** They are end-to-end encrypted; no key to them exists outside the devices in the conversation. |
| That two people have a conversation, and when | The fact and the timing. Encryption hides what was said, not that anyone spoke. |
| Account details | Handle, email address, and account timestamps. |

The messages row is not a policy we could revise under pressure — there is nothing stored that we are able to read. See [Private messages](private-messages.md).

## What compliance can you expect?

Here's the honest, useful answer.

!!! info "Initiative gives you the building blocks; your deployment determines your compliance."
    Initiative provides the technical features that support a strong compliance posture. A certification or a legal compliance status, though, always attaches to an **organization and its operations** — so part of the answer is ours and part of it is yours, and which part depends on who runs the server.

**What Initiative provides, either way:**

- **Strong tenant isolation** enforced in the database (see [How your data is kept separate](how-your-data-is-kept-separate.md)).
- **Least-privilege database roles** and no standing all-tenant bypass.
- **Encryption** of sensitive data at rest, HTTPS in transit, and end-to-end encryption for direct messages.
- **Granular access control** (community, initiative, role, and per-item sharing).
- **Audited, time-bound privileged access** instead of permanent back doors.
- **Data export and erasure** tools that support data-subject requests.
- **Configurable retention** for deleted content.
- **Single sign-on (OIDC)** so you can centralize identity, password policy, and account de-provisioning in your existing identity provider.

**If you host it yourself**, the operational half is yours:

- **Data-protection regulations (such as GDPR/CCPA):** your organization is the data controller. Initiative supports the technical side — export, erasure, access control, residency by choice of host — while lawful processing, consent, and records are organizational responsibilities. There is no third-party processor to sign an agreement with; *you* run it.
- **Formal certifications (such as SOC 2, ISO 27001, HIPAA):** achieved by your hosting and processes — key management, backups, monitoring, physical security, staff access.
- **Backups, disaster recovery, monitoring, and patching:** yours to run. See the [administrator guide](../admin/index.md).

**If we host it**, the operational half is ours: running the service, backing it up, keeping it patched and current. What stays with you is what always stays with the organization using a tool — deciding what you collect, why you're allowed to, who in your group may see it, and answering the requests your own members make of you. Regulated data is worth a conversation before you commit to it rather than after.

!!! warning "No legal advice"
    This page describes capabilities, not a legal compliance guarantee. For regulated data, review your specific obligations with a qualified professional and document how your deployment meets them.

## A checklist for administrators

If compliance matters to your group, make sure you:

- [ ] Serve Initiative over **HTTPS** with a valid certificate.
- [ ] Set a **strong, unique server secret** and store it safely.
- [ ] Take **regular, tested backups** of the database and uploaded files.
- [ ] Keep Initiative **updated** to the latest release.
- [ ] Configure **trash retention** to match your data-retention policy.
- [ ] Prefer **single sign-on** so account lifecycle is managed centrally.
- [ ] Review who holds **administrator** and **owner** roles, and who can break glass.

## Related

- [How your data is kept separate](how-your-data-is-kept-separate.md) — the technical isolation model.
- [Private messages](private-messages.md) — what end-to-end encryption covers.
- [Backups & updates](../admin/backups-and-updates.md) — your operational responsibilities if you host it yourself.
- [Reporting a problem](reporting-a-problem.md) — responsible disclosure.
