---
icon: lucide/megaphone
---

# Reporting a problem

If something about Initiative's security doesn't look right, telling someone is the responsible thing to do — and it's appreciated. This page covers both the everyday case and formal vulnerability reports.

## "I can see something I don't think I should"

If you come across data you don't believe you should have access to — another group's content, a project that wasn't shared with you — please report it. It might be a misconfiguration, or it might be a genuine bug worth fixing.

- **On a server your group runs:** tell your **guild or platform administrator** first. They can check whether it's a settings issue.
- **If it looks like a real flaw in Initiative itself:** follow the responsible-disclosure steps below.

Either way, please **don't poke further** than needed to confirm it, and **don't share** what you saw.

## Reporting a security vulnerability

If you've found a genuine security vulnerability in Initiative, please report it **privately** so it can be fixed before it's made public.

!!! warning "Please don't open a public issue for security problems"
    Public issues are visible to everyone, including anyone who might misuse the flaw. Use the private channel below instead.

### How to report

Email **<security@morelitea.com>** with:

- A description of the vulnerability.
- Steps to reproduce it.
- The potential impact.
- A suggested fix, if you have one (optional).

### What to expect

- **Acknowledgment within 48 hours.**
- An estimated **timeline for a fix**.
- A **notification when it's resolved**.
- **Credit in the release notes**, unless you'd prefer to stay anonymous.

## What's in scope

Reports are welcome about:

- The application (the web interface and the service behind it).
- The mobile apps.
- The deployment setup (Docker configuration and related scripts).

Vulnerabilities in third-party dependencies are generally out of scope, but a heads-up about a vulnerable dependency is still appreciated.

## A note on responsible testing

Probing a server you don't own or administer, without permission, isn't okay — even with good intentions. Test against your own deployment, and report what you find rather than exploiting it.

## Related

- [How your data is kept separate](how-your-data-is-kept-separate.md) — what the boundaries are supposed to be.
- [Security & privacy](index.md) — the everyday overview.
