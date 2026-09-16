---
icon: lucide/clipboard-check
---

# Control mapping

This page maps the access controls auditors usually ask about to what Initiative actually does, and says plainly where it does nothing yet.

It exists because a control with no written account of it is hard to evidence. Where a framework marks a specification *addressable* rather than required — several of the HIPAA Security Rule's are — the accepted answer is to implement it or document the alternative. This is that document.

!!! info "Capabilities, not certification"
    Nothing here is a certification claim, and none of it is legal advice. Initiative is software; a compliance status attaches to an organization and how it runs. See [Data & compliance](data-and-compliance.md) for how that split works.

## How to read this

**Built in** means the control is enforced by the software, on every deployment, without configuration.

**Yours to configure** means the mechanism exists and the setting is yours.

**Not yet** means exactly that. It is listed rather than omitted, because the gaps are what an auditor will ask about and a map with holes painted over is worse than no map.

Where Initiative enforces something in the database rather than in application code, that is noted — it is the difference between a control you can demonstrate and one you have to be trusted on.

## Identity and access

| Control | Commonly asked by | State |
|---|---|---|
| Unique user identification | HIPAA §164.312(a)(2)(i), PCI DSS 8 | **Built in.** Every account is a distinct record; native devices are individually named, listed and revocable. Shared logins are not a supported pattern. |
| Person or entity authentication | HIPAA §164.312(d) | **Built in.** Password or single sign-on, with the account lifecycle centralizable in your identity provider. |
| Multi-factor authentication for all access | PCI DSS 8.4.2 | **Not yet.** Available today only by requiring it at your identity provider and requiring SSO for the community. Initiative enforces no second factor of its own. |
| Role-based access control | SOC 2 CC6.1 | **Built in, database-enforced.** Community, initiative, role and per-item sharing, applied by Postgres row-level security rather than by a query filter. |
| Tenant isolation | all | **Built in, database-enforced.** Each community's content lives in its own schema, reached only by assuming that community's database role. See [How your data is kept separate](how-your-data-is-kept-separate.md). |
| Emergency access procedure | HIPAA §164.312(a)(2)(ii) | **Built in.** Break-glass access is time-bound, per-community, self-approved in one recorded step, and expires on its own. The grant record is the trail. **Gap:** it does not yet emit an audit event on a trail distinct from ordinary access, which is what an emergency-access review usually expects. |
| Access provisioning and prompt de-provisioning | SOC 2 CC6.2 / CC6.3 | **Partial.** Provisioning from your identity provider's groups is supported. De-provisioning is applied when the person next signs in, not pushed the moment your directory changes — there is no SCIM endpoint yet, so removal is not immediate. |
| Periodic access review, with artifacts | SOC 2 CC6.2 | **Not yet.** Membership and sharing are visible in the app, but there is no per-community export to hand an auditor. |

## Sessions

| Control | Commonly asked by | State |
|---|---|---|
| Session expiry | SOC 2 CC6.1 | **Built in.** Sign-in issues a short-lived credential, renewed quietly in the background, plus a rotating renewal token that is replaced every time it is used. |
| Automatic logoff after inactivity | HIPAA §164.312(a)(2)(iii) *(addressable)*, PCI DSS 8.2.8 (15 minutes) | **Not yet, at the durations these ask for.** A session ends after 30 days of not using the app, which is an inactivity bound but not a short one. There is no configurable idle timeout, and no way to set the 15 minutes PCI DSS asks for. **Documented alternative:** deployments needing a short idle timeout should enforce it at the network or device layer — a reverse proxy, a VPN, or managed-device policy. |
| Revocation | SOC 2 CC6.1 | **Built in.** Changing a password ends every session and revokes every device. Individual devices can be revoked one at a time. |
| Credential replay detection | — | **Built in.** A renewal token is single-use; presenting a spent one ends the whole chain of sessions descending from it and records the event. |

## Audit

| Control | Commonly asked by | State |
|---|---|---|
| Audit controls | HIPAA §164.312(b), SOC 2 CC7, PCI DSS 10 | **Partial.** Authentication and moderation are recorded: sign-in, refused sign-in, sign-out, password change, identity linked, replay detected, native credential issued, used and exchanged; and the moderation actions taken against an account. Ordinary reads and writes of content are not recorded. |
| Audit immutability | PCI DSS 10.5, SOC 2 CC7 | **Built in, database-enforced.** The audit table is append-only by grant: the system role may read and insert, `UPDATE` and `DELETE` are granted to nobody at all, and the request path cannot reach it in either direction. |
| Audit retention | PCI DSS 10.5 (12 months, 3 immediately available), HIPAA §164.316(b)(2) (6 years for documentation) | **Not yet.** Records are kept indefinitely and there is no retention setting, no archive and no expiry. **Documented alternative:** take database backups on a schedule that satisfies your own retention obligation. |
| Audit export to your own systems | SOC 2 CC7 | **Not yet.** There is no export endpoint or log shipper. Records are readable in the database. |
| Records survive erasure of the person | SOC 2 CC7 | **Built in, deliberate.** Audit records reference accounts by number and resolve names only when read, so erasing an account leaves the record of what happened without leaving the person in it. |

## Data protection

| Control | Commonly asked by | State |
|---|---|---|
| Encryption in transit | all | **Yours to configure.** Initiative expects to be served over HTTPS; terminating TLS is the deployment's job. |
| Encryption at rest | all | **Partial, and specific.** Sensitive fields — addresses, identity-provider secrets, stored third-party credentials — are encrypted with a key derived from your server secret. Whole-disk or whole-database encryption is your host's to provide. |
| End-to-end encryption | — | **Built in** for direct messages. See [Private messages](private-messages.md). |
| Least privilege for the software itself | SOC 2 CC6.1 | **Built in.** The application connects as three separate database logins with different rights, and holds no superuser credentials. No user-facing role can bypass row-level security. |
| Data export and erasure | GDPR, CCPA | **Built in.** Export and erasure tools support data-subject requests. |
| Data residency | GDPR | **Yours to configure**, by choosing where you host. |

## Change management

| Control | Commonly asked by | State |
|---|---|---|
| Change management for the software | SOC 2 CC8 | **Built in to the engineering process, not to your deployment.** Database changes are frozen once released and can only be corrected by a further change; privileged database grants are checked against a registry in continuous integration; data migrations assert how many rows they touched. These are the vendor's controls over the software you run, not controls you operate. |

## What this means for an administrator

The short version: Initiative's strongest controls are **isolation, least privilege and append-only audit**, all enforced by the database rather than by application code, which is the kind an auditor can be shown rather than told about.

The weakest areas today are **timing and evidence** — no short idle timeout, no audit retention policy, no access-review export, no audit export, and no second factor of Initiative's own.

If those matter to you:

- Require **single sign-on** and enforce MFA, password policy and de-provisioning at your identity provider.
- Enforce a short **idle timeout** at the network or device layer if one is required of you.
- Set a **backup schedule** that satisfies your audit-retention obligation, since the software has no retention setting.
- Keep the **checklist** in [Data & compliance](data-and-compliance.md) — it covers the operational half.

## Related

- [Data & compliance](data-and-compliance.md) — who is responsible for what.
- [How your data is kept separate](how-your-data-is-kept-separate.md) — the isolation model in detail.
- [Single sign-on](../admin/single-sign-on.md) — centralizing identity.
