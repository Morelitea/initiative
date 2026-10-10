---
icon: lucide/megaphone
---

# Reporting a problem

If something about Initiative's security doesn't look right, telling someone is the responsible thing to do — and it's appreciated. This page covers both the everyday case and formal vulnerability reports.

## "I can see something I don't think I should"

If you come across data you don't believe you should have access to — another group's content, a project that wasn't shared with you — please report it. It might be a misconfiguration, or it might be a genuine bug worth fixing.

- **On a server your group runs:** tell your **community's admin, or whoever runs the server**, first. They can check whether it's a settings issue.
- **If it looks like a real flaw in Initiative itself:** follow the responsible-disclosure steps below.

## A problem with this server

To tell whoever runs the server you use about a security problem, choose **Report a security problem**: it's under **User settings → Security**, in **My Tickets**, and in the command palette. Say what it's about, what you found, and attach a screenshot if it helps. The people who run the server read it, and you follow it, and talk with them about it, in **My Tickets**. Where the server isn't set up to take these reports, you're shown the address to write to instead.

From outside, a server says where to send these at `/.well-known/security.txt`. That file names its security address and, where reports are taken in the app, the form.

**If an email says your account changed and it wasn't you**, choose **This wasn't me** in it. Your account is signed out everywhere, and the people who run the server are told; where nobody is set up to hear it, the page names who to tell.

A problem with **this server** goes to the people who run it. A problem with **the Initiative software itself**, which every server running it would have, goes to the project, below.

Either way, please **don't poke further** than needed to confirm it, and **don't share** what you saw.

## Content that shouldn't be there

For something somebody posted — a comment, a notice, a picture, a profile — use **Report** on it. Anything a community holds goes to that community's moderators, and anything about an account goes to whoever runs the server.

## Reporting a security vulnerability

If you've found a genuine security vulnerability in Initiative, please report it **privately** so it can be fixed before it's made public.

!!! warning "Please don't open a public issue for security problems"
    Public issues are visible to everyone, including anyone who might misuse the flaw. Use the private channel below instead.

### How to report

Email **<security@beyonders.studio>** with:

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
- The mobile and desktop apps.
- The deployment setup (Docker configuration and related scripts).

Vulnerabilities in third-party dependencies are generally out of scope, but a heads-up about a vulnerable dependency is still appreciated.

## A note on responsible testing

Probing a server you don't own or administer, without permission, isn't okay — even with good intentions. Test against your own deployment, and report what you find rather than exploiting it.

## Related

- [How your data is kept separate](how-your-data-is-kept-separate.md) — what the boundaries are supposed to be.
- [Security & privacy](index.md) — the everyday overview.
