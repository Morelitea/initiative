---
icon: lucide/key-square
---

# Single sign-on (OIDC)

Single sign-on lets people into Initiative with an account they already have — the work one, a Google one, the passkey thing you run on a box under the stairs. Initiative speaks **OpenID Connect**, which nearly everything speaks, and you set it up in **Settings → Platform → Authentication** as the [owner](platform-roles.md).

You can add as many providers as you want. Each becomes a button on the sign-in page, and whichever button somebody uses, they land in the same one account.

!!! info "Set APP_URL before you start"
    Signing in works by sending the browser away and catching it on the way back, so Initiative has to know its own public address. Set **`APP_URL`** (see [Configuration](configuration.md)) first, or the callback URLs you copy out of here will point at somewhere that isn't you.

## Adding a provider

**Add provider** walks you through it, because this is a conversation between two screens: a couple of values come from your provider, and one has to go back the other way.

**1. Which one.** Pick it from the grid. Ten of them are here by name; **OpenID Connect** at the end is for anything else that speaks it.

**2. Where it lives.** This is the field people get wrong, so it's the field the wizard is strictest about. Pick Keycloak and it asks for your address and your realm, separately, and builds the issuer out of them — nobody should be editing the middle of a URL to insert the word `main`. Then hit **Verify**.

Verify actually goes and asks. If something answers and agrees it's the issuer you named, you get a tick and a short list of what it found. If nothing answers, or the thing that answers is for a different issuer, you find out here rather than three days later when somebody tries to sign in. You can't move on until it's happy — which is the point.

**3. Credentials.** The **Callback URL** is at the top, with a copy button, because it's the one value that travels from here to there. Register it at your provider first; it will refuse the sign-in until that exact address is on its list. Then paste back the **Client ID** and **Client secret** it gives you. Leave the secret blank for a public, PKCE-only client.

**4. How it behaves.**

| Field | What to enter |
|---|---|
| **Slug** | Lowercase letters, numbers and dashes. It forms the sign-in URLs, so it's fixed once you save. |
| **Display name** | What the button says. "Work account" helps more than "OIDC". |
| **Scopes** | Filled in from what your provider said it offers. Add `offline_access` if you want group changes picked up between sign-ins. |
| **Groups claim** | Suggested from the claims your provider listed, and you can type one it didn't. Only needed if you're sorting people into communities — see below. |
| **Create accounts on first sign-in** | On, a stranger who signs in gets an account. Off, the button only works for people who already have one. |
| **Enabled** | Off takes the button away without losing anything you typed. |

Two more addresses sit at the top of the page — a post-login redirect and a mobile app callback — shared by every provider. Most providers never ask for them.

**Afterwards.** Each row has **Test**, which re-asks the same question of a provider you've already saved — useful when somebody has been reorganising things at the other end. **Edit** is a single form rather than four steps, with the same **Verify** button and the same callback to copy. The secret is write-only: leave it blank to keep the one you have, or tick **Remove the stored secret**.

Deleting is careful on your behalf. A provider that a community's sign-in requirement points at waits until you change that requirement. So does one that is somebody's only way in — those people need a password or a second provider first. Everyone else keeps their account and every other way they had of reaching it.

!!! screenshot "Settings → Platform → Authentication"
    Capture the page with two or three providers in the list, and the wizard's address step showing a green Verify result. Save as `docs/en/images/admin/oidc-settings.png`.

## Ways in

At the top of the Authentication page is the list of ways people may sign in to this server. Tick the ones you want. At least one stays on, which the page enforces by refusing to let you untick the last.

| Way in | What it covers |
|---|---|
| **Password** | An email address and a password held here — the sign-in form, registration, and password reset, together. |
| **Single sign-on** | Every provider on this page, and every provider a community has of its own. |

Untick something people are using and Initiative tells you how many accounts sign in only that way, and asks you to confirm that number before it goes through. Nobody is signed out either way — an open session runs to its normal end, on the web and on a phone, and app credentials carry on working. This is about opening a new session, not ending existing ones.

Turning off single sign-on waits if any community still requires one. Lift the requirement there first; the page names how many are in the way.

## Letting a community use a provider

**The providers are yours. A community connects to one.**

You say this deployment can sign people in with Google. A community says *our* members come in through that — and only our Workspace. That second half is the point: Google will vouch for anybody with a Google account, so a community connecting to it names the domain that's theirs.

A community never sees an issuer, a client ID or a secret, and never types an address. There's nothing left for them to get wrong on behalf of every one of their members.

A community bringing its own identity provider is the same shape with you doing the registering: add their Okta on this page when you onboard them, and connect it to them.

**The three ticks** in **Settings → Platform → Guilds → Manage → Sign-in** are yours to grant, per community. The first one turns the others on.

| Option | What it lets their admins do |
|---|---|
| **Configuring its own sign-in** | Gives the community an Authentication page at all — and with it, personal API keys and a twelve-hour session limit. Off to start with, which is the right answer for most communities: they never see the page. |
| **Its own sign-in providers** | Connect to the providers you've registered, say which accounts on one count as theirs, and copy a member sign-in link that drops people straight into the community. |
| **Requiring a sign-in** | Insist members reach the community through one of those connections. |

The last two are separate on purpose. A community can offer a sign-in as a convenience without forcing anyone through it.

Withdrawing an option closes the page it governs and nothing else. Their connections stay, their members keep signing in, and a requirement they already set stays in force — you're taking away the ability to change the setup, not the setup. Their admins can always lift a requirement, whatever you've granted, so a community is never stuck behind a sign-in nobody can undo.

Withdrawing the first takes the page away entirely; withdrawing either of the others closes the part it governs and nothing else. Their connections stay, their members keep signing in, and a requirement they already set stays in force — you're taking away the ability to change the setup, not the setup. Their admins can always lift a requirement, whatever you've granted, so a community is never stuck behind a sign-in nobody can undo.

Everybody still has exactly one account however they signed in.

## Provider quickstarts

Any standards-compliant OIDC provider works, and the wizard already knows each of these spells its issuer differently — it asks for the parts and assembles the address. What's left is the bit you do at the other end.

=== "Pocket ID"

    Passkey-only and light on its feet, which makes it a common pairing.

    1. **OIDC Clients → Add client**, name it "Initiative".
    2. Set its **Callback URL** to the one the wizard is showing you.
    3. Copy the generated **Client ID** and **Client secret** back in.

    The wizard asks for your Pocket ID **Address**. Nobody has a password in Pocket ID, so your Initiative sign-ins inherit passkeys without you doing anything. For group sorting, turn groups on there and pick `groups` as the **Groups claim**.

=== "Authentik"

    1. Create a **Provider → OAuth2/OpenID**, set its **Redirect URI** to the callback URL the wizard is showing you, and note the **Client ID** and **Client secret**.
    2. Create an **Application** and bind the provider to it.

    The wizard asks for your **Address** and the **Application slug** — the application's, not the provider's, which is the one people mix up. For group sorting, add the `groups` scope there and pick `groups` as the **Groups claim**.

=== "Authelia"

    Configured in YAML rather than a screen.

    1. Under `identity_providers.oidc.clients`, add a client with a `client_id`, a **hashed** `client_secret`, `redirect_uris` set to the callback URL the wizard is showing you, and `scopes: [openid, profile, email, groups]`.
    2. Restart Authelia.

    The wizard asks for your Authelia **Address**. The secret you paste back is the **plaintext** one, not the hash you put in the YAML.

=== "Keycloak"

    1. In your realm, create an OpenID Connect **Client** with **Client authentication** on and a **Valid redirect URI** of the callback URL the wizard is showing you.
    2. The **Client secret** is on the client's **Credentials** tab; the **Client ID** is the client name.

    The wizard asks for your **Address** and your **Realm** and builds the issuer from both. For group sorting, add a groups or roles mapper and pick `groups` or `realm_access.roles` as the **Groups claim**.

=== "Google, Entra, Okta, Auth0"

    Same shape: register an app, add the callback URL the wizard is showing you, copy the credentials back.

    All four are presets, so the address is one field or none:

    - **Google** asks for nothing — its issuer never varies.
    - **Microsoft Entra ID** asks for your **Tenant ID**.
    - **Okta** asks for your **Okta domain**, like `dev-12345.okta.com`.
    - **Auth0** asks for your **Auth0 domain**, like `your-tenant.eu.auth0.com`.

=== "Zitadel"

    1. Create a project, then an **Application** of type **Web** using **Code** with PKCE.
    2. Set its redirect URI to the callback URL the wizard is showing you.
    3. Copy the **Client ID** and **Client secret** back in.

    The wizard asks for your **Address** — your own domain, or `your-instance.zitadel.cloud`.

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
