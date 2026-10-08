---
icon: lucide/plug
---

# Running plug-ins

Communities add plug-ins from the marketplace. Whether a plug-in can run on your server at all is your decision, and it's made in one place: **Settings → Platform → Integrations**, as the [owner](platform-roles.md).

Most plug-ins need nothing from you. The rest need an address, a key or a few values from another service, and this page is where those go.

## Where plug-ins come from

| | |
|---|---|
| **Ships with Initiative** | Part of the build. Credited to Initiative, and nothing else can claim that. |
| **The Initiative registry** | A signed online catalog your server follows from the moment it starts. See [below](#the-initiative-registry). |
| **Your own directory** | Listing files you publish yourself. See [Publishing your own listings](publishing-listings.md). |

Every plug-in from any of these gets a row under **Plug-in services**. Its listing says what the plug-in is and the most it may ever be granted. The row holds what only your server knows: where it runs, the keys it signs with, and whether it's switched on.

## The Initiative registry

The registry is a catalog of plug-ins, dashboards and projects from BeyondersStudio and the publishers it signs for. Anyone can [propose a listing](publishing-listings.md#publishing-to-the-initiative-registry). Every file it brings is checked against a signing key built into Initiative before anything is used, so a listing arrives exactly as it was published or not at all.

Its panel is **Marketplace registry**, under **Integrations**:

| | |
|---|---|
| **Follow the registry** | Off, the server stops asking for updates. Whatever it already brought stays. |
| **Refresh now** | Checks straight away rather than at the next scheduled check (every fifteen minutes). |
| **Upload a registry bundle** | For a server with no internet access: a `.tar.gz` of the registry's `metadata` and `targets` folders, carried in by hand. It's checked against the same key, so a bundle that went via a USB stick in somebody's coat pocket is exactly as trustworthy as one that didn't. |

The panel also says when it last updated, how many listings came from it, and why the last attempt stopped, if it did. A skipped listing is named with its reason.

The registry re-signs itself every day, so its signatures are always fresh. A server that hasn't reached it in a while says when the ones it holds ran out, and that its listings may be out of date. Nothing it already brought stops working, and the next successful update brings it current.

There's nothing to configure for any of this. A network that can't reach the registry directly can read a mirror instead; see [Configuration](configuration.md#the-initiative-registry-and-plug-ins).

## The two kinds of plug-in

| | **Runs inside Initiative** | **Runs as a container** |
|---|---|---|
| What runs | Nothing extra. Initiative makes the plug-in's calls itself, from its manifest. | The plug-in's own program, beside Initiative. |
| What it needs from you | Its vendor values, if it talks to another service. | Where it answers, the keys it signs with, and any vendor values. |
| Says, on its row | *Initiative makes this plug-in's calls itself.* | *Container image:* and the image it runs. |

A row is **Live** once it has everything it needs, and communities are offered it. Until then it shows **Not live**, with a line saying what's missing, and no community sees it on the Plug-ins shelf.

### A plug-in that runs inside Initiative

If it asks for nothing, it's live already, and this section is over.

If it talks to another service, its row has a **Vendor client** section: the values that service issued for your server, such as a client ID and secret. Initiative keeps them encrypted and uses them to connect communities and members to that service. A secret is never shown again once it's saved; type a new one to replace it.

The row also lists the **Addresses to register with the vendor**: a callback, a setup and a webhook address on your own server. Paste those into the vendor's settings for the client you made.

!!! tip "The GitHub plug-in does all of that for you"
    Its row has **Create the GitHub App**. GitHub opens with the plug-in's permissions, events and your server's addresses already filled in. Confirm it there, optionally under an organization, and GitHub sends the six values back to Initiative. You type and copy none of them.

### A plug-in that runs as a container

1. **Run it.** If its listing includes one, the row shows a **Compose service** with a **Copy** button. Add it to the `docker-compose.yml` that runs Initiative, then `docker compose up -d`.
2. **Edit the row and give it a Base URL**: where Initiative's server calls the plug-in. A private address on your own network is fine, such as `http://tracker:8080` on the Compose network.
3. **Pin its keys.** Press **Connect**. Initiative reads the keys the plug-in serves and shows each one's fingerprint. Check them against the line the plug-in's container logs when it starts (`app key fingerprint: …`), and **Pin these keys** only if they match.

That's it: it goes live.

A pinned key set stays pinned. If the plug-in rotates its keys, press **Connect** again. Two other ways to give it keys, both on the same form:

- **Pasted key set (JWKS)**: the key set the plug-in publishes, pasted in.
- **Key set address**: where the plug-in publishes it, so a rotation needs no visit here. It must be `https`, on the Base URL's own origin.

Two more fields, for plug-ins with pages that open inside Initiative:

- **Browser address**: where a member's browser loads the plug-in's pages, when that differs from the Base URL. A private Compose address works for the server and not for anybody's laptop.
- **Allowed origins**: one per line. Blank allows only the browser address.

### Adding one before its listing arrives

**Add plug-in service** takes the plug-in's identifier (`publisher.plugin-name`) and whatever you already know: its address, its keys. It shows **Waiting for its listing** until the listing turns up, from the registry or your own directory, and fills in the rest.

### Switching one off, and the other switches

| | |
|---|---|
| **Enabled** | Off, every community that added it stops reaching it at once: its data, its settings, its events and its pages. Nothing is deleted. Turn it back on and everything is where it was. A restart never turns it back on for you. |
| **Install in every community** | It's added to every community, including new ones, and community admins can't remove it or turn it off. Shown as **In every community**. |
| **Delete** | Removes the registration for good, and adding it back means registering it again. A plug-in from the registry can't be deleted, because the next update would bring it straight back; switch it off instead. |

A row marked **Publisher switched off** has stopped because everything from that publisher has. Nothing is deleted there either.

## Setting it up from a file

Rather click nothing? `PLUGIN_SERVICES_CONFIG` names a JSON file Initiative reads at every start, and does what you would have done on the form.

```json
[
  {
    "public_id": "acme.tracker",
    "base_url": "http://tracker:8080",
    "page_origin": "https://tracker.example.com",
    "jwks_uri": "https://tracker.example.com/.well-known/jwks.json"
  },
  {
    "public_id": "beyonders-studio.github",
    "vendor_env": {
      "client_id": "GITHUB_APP_CLIENT_ID",
      "client_secret": "GITHUB_APP_CLIENT_SECRET",
      "app_slug": "GITHUB_APP_SLUG",
      "app_id": "GITHUB_APP_ID",
      "private_key": "GITHUB_APP_PRIVATE_KEY",
      "webhook_secret": "GITHUB_APP_WEBHOOK_SECRET"
    }
  }
]
```

| Field | What it is |
|---|---|
| `public_id` | Which plug-in. Required. |
| `base_url` | Where Initiative's server calls it. Giving one gives its browser address and keys with it, and clears whichever of those the entry leaves out. |
| `page_origin` | Its **Browser address**. |
| `jwks` / `jwks_uri` | Its keys, pasted or by address. |
| `allowed_origins` | A list of origins. |
| `mandatory` | `true` installs it in every community. |
| `vendor_env` | Each vendor value, as the name of an environment variable holding it. Read and stored encrypted at every start, so a secret never sits in the file. |

What the plug-in *is* comes from its listing, so an entry naming its image, its scopes or its listing is refused. An entry for a plug-in whose listing hasn't arrived waits for it. And a plug-in you switched off stays off, whatever the file says.

??? techspec "Initiative's own signing key"
    Initiative signs what it sends plug-ins with a key it makes and keeps itself. To supply your own instead, set `PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM` (a PEM from `openssl genrsa 2048`) and `PLUGIN_PLATFORM_SIGNING_KEY_ID`. Most servers never touch either.

## Related

- [Configuration](configuration.md#the-initiative-registry-and-plug-ins) — every setting on this page.
- [Publishing your own listings](publishing-listings.md) — your own directory, and getting a listing into the registry.
- [Plug-ins & the marketplace](../guides/plugins-and-marketplace.md) — what a community sees when it adds one.
