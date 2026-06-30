---
icon: lucide/scale
---

# Data & compliance

This page explains who owns your data, where it lives, the rights you have over it, and — honestly — what compliance posture you can and can't expect. It's written for the people who have to answer these questions for their organization, but the first part is for everyone.

## Who owns your data

**You do.** Initiative is **self-hosted**, which means it runs on hardware your group controls (or a host your group chooses). Your projects, documents, and files live in *your* database and *your* file storage. There's no central company sitting in the middle with a copy.

That's a genuine privacy advantage — and it comes with a responsibility: because you hold the data, you (or whoever administers your server) are responsible for backing it up and looking after it. See [Backups & updates](../admin/backups-and-updates.md).

## Where your data lives (data residency)

Your data lives wherever your server runs. If that's a computer in your office, your data is in your office. If it's a cloud server in a particular country, your data is in that country. **You choose** — which makes meeting data-residency requirements a matter of where you deploy, not something you have to negotiate with a vendor.

## How your data is protected

- **In transit:** run behind HTTPS and all traffic between browsers and the server is encrypted.
- **At rest:** the most sensitive stored fields — saved AI keys, single-sign-on secrets, email-server passwords, and email addresses — are encrypted in the database.
- **Access control:** everything is gated by the [six-layer model](how-your-data-is-kept-separate.md) and enforced in the database.

## Your data rights

### Getting your data out

Initiative is built to avoid locking your information in:

- **Export a project** to a portable file you can keep or re-import elsewhere.
- **Export spreadsheets** as CSV or Excel (XLSX).
- **Export calendar events** as standard `.ics` files.
- Administrators can **export the user list** as CSV.

### Removing data

- **Anything you delete** goes to the **Trash** first, where it can be restored until the retention period passes — then it's permanently removed. Administrators set how long that is (see [Working with guilds](../guides/guilds.md#trash-and-retention)).
- **Your account** can be **deactivated** (you can't sign in, but your content stays) or **deleted**. Deleting offers a choice: *anonymize* (your personal details are removed and your past contributions show as "Deleted user") or, for administrators, *hard delete* (everything is removed). See [Profile & preferences](../account/profile-and-preferences.md).

This directly supports the kind of "right to erasure" and "right to access" requests that privacy regulations expect: you can produce a person's data and remove their personal information.

### Accountability

Sensitive cross-group access is **recorded**. When an administrator or support person uses an emergency "break-glass" grant, or a time-bound access request is approved, that event is logged with who, which guild, and why — so privileged access is auditable rather than invisible.

## What compliance can you expect?

Here's the honest, useful answer.

!!! info "Initiative gives you the building blocks; your deployment determines your compliance."
    Because Initiative is self-hosted, **your organization is the data controller**. Initiative provides the technical features that support a strong compliance posture, but a certification or legal compliance status always depends on *how you deploy and operate it* — your hosting, your backups, your policies, your access governance.

**What Initiative provides toward compliance:**

- **Strong tenant isolation** enforced in the database (see [How your data is kept separate](how-your-data-is-kept-separate.md)).
- **Least-privilege database roles** and no standing all-tenant bypass.
- **Encryption** of sensitive data at rest, and HTTPS in transit.
- **Granular access control** (guild, initiative, role, and per-item sharing).
- **Audited, time-bound privileged access** instead of permanent back doors.
- **Data export and erasure** tools that support data-subject requests.
- **Configurable retention** for deleted content.
- **Single sign-on (OIDC)** so you can centralize identity, password policy, and account de-provisioning in your existing identity provider.

**What depends on you, the operator:**

- **Data-protection regulations (such as GDPR/CCPA):** Initiative supports the technical side (export, erasure, access control, residency by choice of host), but lawful processing, consent, records, and data-processing agreements are organizational responsibilities. There's no third-party processor to sign an agreement with — *you* run it.
- **Formal certifications (such as SOC 2, ISO 27001, HIPAA):** these certify an *organization and its operations*, not just software. Initiative can be a component of a compliant system, but the certification is achieved by your hosting and processes — encryption keys, backups, monitoring, physical security, staff access, and so on.
- **Backups, disaster recovery, monitoring, and patching:** yours to run. See the [administrator guide](../admin/index.md).

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
- [Backups & updates](../admin/backups-and-updates.md) — your operational responsibilities.
- [Reporting a problem](reporting-a-problem.md) — responsible disclosure.
