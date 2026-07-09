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

## Provider-specific setup

Initiative works with **any** standards-compliant OIDC provider — you point it at your own identity provider, and Initiative signs people in against it. In every case the result is the same three values to paste into **Settings → Platform → Auth** — an **Issuer**, a **Client ID**, and a **Client secret** — plus registering the callback URLs Initiative shows you. Use the scopes from the table above.

Here are quickstarts for the providers self-hosters reach for most.

=== "Pocket ID"

    A lightweight, passkey-only provider — a popular pairing with Initiative.

    1. In Pocket ID, go to **OIDC Clients → Add client** and name it "Initiative".
    2. Set the **Callback URL** to the **Authorization callback** shown on Initiative's Auth page.
    3. Save, then copy the generated **Client ID** and **Client secret**.
    4. In Initiative, set **Issuer** to your Pocket ID address (e.g. `https://id.example.com`) and paste the Client ID and secret.

    Because Pocket ID has no passwords, everyone signs in with a passkey — your Initiative sign-ins inherit that automatically. To sort people into guilds, enable groups in Pocket ID and set the **Claim path** to `groups`.

=== "Authentik"

    1. Create a **Provider → OAuth2/OpenID**; set the **Redirect URI** to Initiative's Authorization callback and note the generated **Client ID** and **Client secret**.
    2. Create an **Application** and bind the provider to it.
    3. In Initiative, set **Issuer** to `https://authentik.example.com/application/o/<application-slug>/` and paste the Client ID and secret.
    4. For group mapping, add the `groups` scope to the provider and set Initiative's **Claim path** to `groups`.

=== "Authelia"

    Authelia's OIDC is configured in its YAML, not a UI.

    1. Under `identity_providers.oidc.clients`, add a client with a `client_id`, a **hashed** `client_secret`, `redirect_uris` (Initiative's Authorization callback), and `scopes: [openid, profile, email, groups]`.
    2. Restart Authelia to apply.
    3. In Initiative, set **Issuer** to your Authelia address (e.g. `https://auth.example.com`), and paste the Client ID and the **plaintext** secret.

=== "Keycloak"

    1. In your realm, create a **Client** (OpenID Connect) with **Client authentication** on, and set a **Valid redirect URI** to Initiative's Authorization callback.
    2. From the client's **Credentials** tab copy the **Client secret**; the **Client ID** is the client name.
    3. In Initiative, set **Issuer** to `https://keycloak.example.com/realms/<realm>` and paste the Client ID and secret.
    4. For roles, add a **groups** (or roles) mapper to the client and set Initiative's **Claim path** to `groups` (or `realm_access.roles`).

=== "Entra / Google / Okta"

    Hosted providers work the same way — register an app, add Initiative's callback URL, and copy the Issuer, Client ID, and secret.

    - **Microsoft Entra ID** issuer: `https://login.microsoftonline.com/<tenant-id>/v2.0`
    - **Google** issuer: `https://accounts.google.com`
    - **Okta** issuer: `https://<your-org>.okta.com`

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
