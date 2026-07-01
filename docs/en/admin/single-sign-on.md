---
icon: lucide/key-square
---

# Single sign-on (OIDC)

Single sign-on (SSO) lets people sign in to Initiative with an account they already have — from a provider like Microsoft Entra ID, Google, Okta, Keycloak, or Authentik. Initiative supports the **OpenID Connect (OIDC)** standard. You configure it from **Settings → Platform → Auth** as the [owner](platform-roles.md).

## Why use it

- People don't manage a separate Initiative password.
- Your existing password policy, multi-factor authentication, and account de-provisioning apply automatically.
- You can **map groups from your provider** to Initiative guilds and roles, so the right people land in the right place on first sign-in.

!!! info "Make sure APP_URL is set and reachable"
    OIDC relies on redirecting back to Initiative at known URLs. Set **`APP_URL`** to your real public address (see [Configuration](configuration.md)) before configuring SSO, or the callback URLs will be wrong.

## Setting it up

In **Settings → Platform → Auth**, you'll provide:

| Field | What to enter |
|---|---|
| **Enabled** | Turn SSO on. |
| **Issuer** | Your provider's base URL (e.g. `https://accounts.example.com`). |
| **Client ID** | The client/application ID from your provider. |
| **Client secret** | The matching secret. (Leave blank when editing to keep the existing one.) |
| **Provider name** | The label on the sign-in button (e.g. "Company Login"). |
| **Scopes** | Usually `openid profile email offline_access`. |

Initiative shows you the **callback URLs** to register back in your provider:

- **Authorization callback** — the main redirect URL.
- **Post-login redirect** — where users land after signing in.
- **Mobile app callback** — for sign-in from the mobile apps.

Copy these into your identity provider's app/client configuration.

!!! screenshot "OIDC settings"
    **Show:** the Auth settings page with the Issuer, Client ID/secret, Provider name, Scopes fields and the callback URLs.

    Save as `en/images/admin/oidc-settings.png`, then use:
    `![OIDC single sign-on settings](../images/admin/oidc-settings.png)`

## Mapping provider groups to guilds and roles

This is the powerful part. You can have Initiative read a **claim** from the sign-in token (for example, the user's groups or roles at your provider) and automatically place them into guilds and initiatives.

1. Set the **Claim path** — the dot-notation location of the claim in the token (for example, `roles`, or `realm_access.roles` for Keycloak).
2. Add **mapping rules**. Each rule matches a **claim value** and assigns:
    - a **target type**: *Guild only*, or *Guild + Initiative*;
    - the **guild** (and **guild role**: Member or Admin);
    - optionally the **initiative** and **initiative role**.

So a rule might say: *anyone whose `roles` claim contains `theatre-leads` becomes an **Admin** of the "Riverside Players" guild.* New people from your provider are sorted automatically the first time they sign in.

??? techspec "For the technically minded — how the mapping is evaluated"
    On each OIDC sign-in, Initiative reads the configured claim path from the ID token, then applies every matching rule to grant the corresponding guild/initiative memberships and roles. PKCE is used in the authorization flow. Mappings are applied idempotently per sign-in, so they reconcile membership rather than duplicating it.

## Related

- [Configuration](configuration.md) — `APP_URL` and other foundational settings.
- [Platform roles](platform-roles.md) — who can configure SSO.
- [Signing in](../getting-started/signing-in.md) — the user's view of SSO.
