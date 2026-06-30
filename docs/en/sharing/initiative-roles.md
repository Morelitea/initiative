---
icon: lucide/shield-user
---

# Initiative roles

Within an initiative, every member has a **role**. A role is a reusable bundle of permissions that decides which *kinds of tools* a person can use here. Roles save you from setting permissions person by person — you describe the *kind* of member once, then assign it.

## How roles fit with sharing

It helps to separate two different questions:

- **Roles** answer *"what kinds of things can this person do in this initiative?"* — for example, "can they create projects, or only view them?"
- **Sharing** answers *"can this person see this **specific** project or document?"* — covered in [Sharing projects & documents](sharing-projects-and-documents.md).

Both apply. A role might let someone create documents in general, while an individual document is still only visible to the people it's shared with.

## The permissions a role can grant

Permissions are grouped by tool. For each tool, a role can typically allow **viewing**, **creating**, or neither:

| Tool | Permissions |
|---|---|
| **Projects** | View, Create |
| **Documents** | View, Create |
| **Queues** | View, Create |
| **Counters** | View, Create |
| **Events** (calendar) | View, Create |
| **Advanced tool** | Open, Create |

So a "Contributor" role might be allowed to view and create projects and documents, while a "Guest" role can only view them, and has no access to queues or counters at all.

!!! screenshot "A role's permissions"
    **Show:** the initiative "Roles" settings with a role selected and its grid of view/create permission checkboxes.

    Save as `en/images/sharing/role-permissions.png`, then use:
    `![A role's permissions](../images/sharing/role-permissions.png)`

## The built-in Manager role

Every initiative includes a **Manager** role (also called the project manager, or PM). It's the lead role: its permissions are fixed and broad, and whoever creates an initiative starts as its Manager.

The Manager role is also the **only** role with **full access** — Managers can reach **everything** in the initiative, including projects and documents that were never shared with them individually. This override belongs to Manager alone; no other role, built-in or custom, can be given it.

!!! warning "Managers see everything — choose them carefully"
    Because the Manager role overrides per-item sharing, anything kept private to a few people is still visible to a Manager. Give the Manager role only to the few people who genuinely need the whole picture.

## Creating your own roles

Beyond Manager, you can create roles that match how your group actually works:

1. Open the initiative's **settings → Roles**.
2. **Add a role** and give it a name your group will recognize ("Director," "Cast," "Editor," "Observer").
3. Tick the permissions it should have.
4. Save. The role is now available when you add or edit members.

Name roles for *people*, not permissions — "Volunteer" is friendlier and clearer than "View-only contributor."

## Assigning roles to members

When you [add a member to an initiative](../guides/initiatives.md#adding-members), you choose their role. You can change someone's role later from the same **Members** settings. Changes take effect right away.

## Related

- [Sharing projects & documents](sharing-projects-and-documents.md) — the final, per-item layer.
- [Working with initiatives](../guides/initiatives.md) — creating initiatives and adding members.
