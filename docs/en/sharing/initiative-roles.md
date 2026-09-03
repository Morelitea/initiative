---
icon: lucide/shield-user
---

# Initiative roles

Every member of an initiative holds a **role** — a reusable bundle of permissions that decides which *kinds of tools* they can use here.

Roles save you setting permissions person by person. Describe the *kind* of member once, then hand it out.

## Roles vs. sharing

Two different questions, and both apply:

- **Roles** answer *"what kinds of things can this person do in this initiative?"* — can they make projects, or only look at them?
- **Sharing** answers *"can this person see this **specific** project or document?"* — covered in [Sharing projects & documents](sharing-projects-and-documents.md).

So a role might let somebody create documents in general, while an individual document is still only visible to the handful of people it's been shared with. Both things are true at once and they don't fight.

## What a role can grant

Permissions are grouped by tool, and each offers **View**, **Create**, or neither:

| Tool | Permissions |
|---|---|
| **Projects** | View, Create |
| **Documents** | View, Create |
| **Queues** | View, Create |
| **Counters** | View, Create |
| **Events** (calendar) | View, Create |
| **Dashboards** | View, Create |

So a "Contributor" might view and create projects and documents, while a "Guest" only views them and has no idea the queues exist.

![A role's permissions](../images/sharing/role-permissions.png)

## The built-in Manager role

Every initiative comes with a **Manager** role (also called project manager, or PM). It's the lead role: fixed permissions, broad ones, and whoever creates an initiative starts as its Manager.

Manager is also the **only** role with **full access** — Managers reach everything in the initiative, including projects and documents that were never shared with them personally. No other role, built-in or custom, can be given this. It isn't a setting you've failed to find.

!!! warning "Managers see everything. Everything."
    Because Manager overrides per-item sharing, anything kept private to a few people is still perfectly visible to one.

    So hand it to the people who genuinely need the whole picture — not as a general reward for being helpful, and not because someone's been around a long time.

## Making your own roles

1. Open the initiative's **settings → Roles**.
2. **Add a role** and name it something your group will actually recognise: "Director", "Cast", "Editor", "Observer".
3. Tick what it should be allowed to do.
4. Save. It's available next time you add or edit a member.

Name roles for *people*, not for permissions. "Volunteer" is friendlier and clearer than "View-only contributor", and nobody has ever been pleased to be called a view-only contributor.

## Handing them out

When you [add a member](../guides/initiatives.md#adding-members), you pick their role. Change it later from the same **Members** settings — changes take effect immediately, no re-login, no waiting.

## Related

- [Sharing projects & documents](sharing-projects-and-documents.md) — the final, per-item layer.
- [Working with initiatives](../guides/initiatives.md) — creating initiatives and adding members.
