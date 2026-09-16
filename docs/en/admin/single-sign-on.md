---
icon: lucide/key-square
---

# Single sign-on (OIDC)

Single sign-on lets people into Initiative with an account they already have — the work one, a Google one, the passkey thing you run on a box under the stairs. Initiative speaks **OpenID Connect**, which nearly everything speaks, and you set it up in **Settings → Platform → Authentication** as the [owner](platform-roles.md).

You can add as many providers as you want. Each becomes a button on the sign-in page, and whichever button somebody uses, they land in the same one account.

!!! info "Set APP_URL before you start"
    Signing in works by sending the browser away and catching it on the way back, so Initiative has to know its own public address. Set **`APP_URL`** (see [Configuration](configuration.md)) first, or the callback URLs you copy out of here will point at somewhere that isn't you.

## Adding a provider

**Add provider** opens a short form. The **Preset** picker fills in the unchanging parts for Google and Microsoft. Everything else is **Custom**, which is a blank OIDC form — Keycloak, Authentik, Authelia, Zitadel and Pocket ID all take one.

| Field | What to enter |
|---|---|
| **Slug** | Lowercase letters, numbers and dashes. It forms the sign-in URLs, so it's fixed once you save. |
| **Display name** | What the button says. "Work account" helps more than "OIDC". |
| **Issuer URL** | Your provider's base address, like `https://id.example.com`. |
| **Client ID** and **Client secret** | From the app you register at your provider. Leave the secret blank for a public, PKCE-only client. |
| **Scopes** | `openid email profile` covers it. Add `offline_access` if you want group changes picked up between sign-ins. |
| **Groups claim** | Where this provider keeps a person's groups. Only needed if you're sorting people into communities — see below. |
| **Create accounts on first sign-in** | On, a stranger who signs in gets an account. Off, the button only works for people who already have one. |
| **Enabled** | Off takes the button away without losing anything you typed. |

Save, and the row shows its **Callback URL**. That's the one value your identity provider wants back from you. Two more addresses sit at the top of the page — a post-login redirect and a mobile app callback — shared by every provider, and most IdPs never ask for them.

Editing is the same form. The secret is write-only: leave it blank to keep the one you have, or tick **Remove the stored secret**.

Deleting is careful on your behalf. A provider that a community's sign-in requirement points at waits until you change that requirement. So does one that is somebody's only way in — those people need a password or a second provider first. Everyone else keeps their account and every other way they had of reaching it.

!!! screenshot "Settings → Platform → Authentication"
    Capture the page with two or three providers in the list, one row expanded to show its callback URL. Save as `docs/en/images/admin/oidc-settings.png`.

## Ways in

At the top of the Authentication page is the list of ways people may sign in to this server. Tick the ones you want. At least one stays on, which the page enforces by refusing to let you untick the last.

| Way in | What it covers |
|---|---|
| **Password** | An email address and a password held here — the sign-in form, registration, and password reset, together. |
| **Single sign-on** | Every provider on this page, and every provider a community has of its own. |

Untick something people are using and Initiative tells you how many accounts sign in only that way, and asks you to confirm that number before it goes through. Nobody is signed out either way — an open session runs to its normal end, on the web and on a phone, and app credentials carry on working. This is about opening a new session, not ending existing ones.

Turning off single sign-on waits if any community still requires one. Lift the requirement there first; the page names how many are in the way.

## Letting a community run its own sign-in

A community can have identity providers of its own — useful when it's a separate organisation with a separate staff directory. That's yours to grant, per community, in **Settings → Platform → Guilds**: find it in the list, hit **Manage**, and the **Sign-in** section has two ticks.

| Option | What it lets their admins do |
|---|---|
| **Its own sign-in providers** | Add providers on their own Authentication page, copy a member sign-in link that drops people straight into the community, and onboard new accounts through it. |
| **Requiring a sign-in** | Insist members reach the community through one of those providers. |

They're separate on purpose. A community can offer its provider as a convenience without forcing anyone through it — those are different arrangements, and one used to imply the other.

A community's own provider only ever admits people to that community, and everybody still has exactly one account however they signed in.

Withdrawing an option closes the page it governs and nothing else. Their providers stay, their members keep signing in through them, and a requirement they already set stays in force — you're taking away the ability to change the setup, not the setup. Their admins can always lift a requirement, whatever you've granted, so a community is never stuck behind a sign-in nobody can undo.

## Provider quickstarts

Any standards-compliant OIDC provider works. In every case you end up with the same three values — an **Issuer URL**, a **Client ID** and a **Client secret** — plus the callback URL registered at the other end.

=== "Pocket ID"

    Passkey-only and light on its feet, which makes it a common pairing.

    1. **OIDC Clients → Add client**, name it "Initiative".
    2. Set its **Callback URL** to the one on Initiative's provider row.
    3. Copy the generated **Client ID** and **Client secret**.
    4. In Initiative, set the **Issuer URL** to your Pocket ID address and paste both in.

    Nobody has a password in Pocket ID, so your Initiative sign-ins inherit passkeys without you doing anything. For group sorting, turn groups on there and set the **Groups claim** to `groups`.

=== "Authentik"

    1. Create a **Provider → OAuth2/OpenID**, set its **Redirect URI** to Initiative's callback URL, and note the **Client ID** and **Client secret**.
    2. Create an **Application** and bind the provider to it.
    3. In Initiative, the **Issuer URL** is `https://authentik.example.com/application/o/<application-slug>/`.
    4. For group sorting, add the `groups` scope there and set the **Groups claim** to `groups`.

=== "Authelia"

    Configured in YAML rather than a screen.

    1. Under `identity_providers.oidc.clients`, add a client with a `client_id`, a **hashed** `client_secret`, `redirect_uris` set to Initiative's callback URL, and `scopes: [openid, profile, email, groups]`.
    2. Restart Authelia.
    3. In Initiative, the **Issuer URL** is your Authelia address, and the secret you paste is the **plaintext** one, not the hash.

=== "Keycloak"

    1. In your realm, create an OpenID Connect **Client** with **Client authentication** on and a **Valid redirect URI** of Initiative's callback URL.
    2. The **Client secret** is on the client's **Credentials** tab; the **Client ID** is the client name.
    3. In Initiative, the **Issuer URL** is `https://keycloak.example.com/realms/<realm>`.
    4. For group sorting, add a groups or roles mapper and set the **Groups claim** to `groups` or `realm_access.roles`.

=== "Entra, Google, Okta"

    Same shape: register an app, add Initiative's callback URL, copy the three values. Google and Microsoft have presets, so you only supply the credentials.

    - **Microsoft Entra ID**: `https://login.microsoftonline.com/<tenant-id>/v2.0`
    - **Google**: `https://accounts.google.com`
    - **Okta**: `https://<your-org>.okta.com`

## Sorting people into communities

If your provider already knows who's in which group, Initiative can read that and put people where they belong the moment they first sign in. No invite, no waiting for somebody to notice the email.

Two parts to it. On the provider, set the **Groups claim** to wherever it keeps them — `groups` for most, `realm_access.roles` for Keycloak. Then add **mapping rules** further down the page. Each rule names:

- the **provider** whose claim it reads;
- the **claim value** to match, like `theatre-leads`;
- whether it grants a **community**, or a community **and an initiative**;
- and the role to give in each.

So one rule can say: anyone whose `groups` claim contains `theatre-leads` becomes an **Admin** of Riverside Players.

A rule belongs to one provider, because two providers can both have a group called `staff` and mean entirely different people. Signing in through one neither reads the other's rules nor undoes what they did.

Every sign-in re-reads the claim and reconciles against it, so somebody dropped from a group at your provider loses what that rule gave them. Memberships you granted by hand are left alone — the rules only ever take back what they handed out.

??? techspec "How the mapping is evaluated"
    On each sign-in Initiative reads the provider's claim path from the ID token, falling back to the userinfo response, and applies every rule belonging to that provider. The authorization flow uses PKCE. Reconciliation is idempotent and scoped to the signing-in provider on both halves: it grants what that provider's rules match, and releases only the memberships that same provider's earlier syncs created. Where a provider supplies a refresh token (`offline_access`), a background sweep re-reads group claims for every provider that asserts one about every quarter of an hour, so changes land without waiting for the person to sign in again.

## Related

- [Configuration](configuration.md) — `APP_URL` and the rest.
- [Platform roles](platform-roles.md) — who can configure this.
- [Signing in](../getting-started/signing-in.md) — what people see.
