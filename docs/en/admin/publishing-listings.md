---
icon: lucide/package-plus
---

# Publishing your own listings

Initiative's marketplace ships with a set of ready-made dashboards and apps. It's also **yours to add to**: point Initiative at a directory, drop a listing file in it, and that listing appears in your marketplace beside the built-in ones — ready for anyone in your communities to install.

Nothing about this needs a fork, a code change, or a new build of Initiative. If you've designed a dashboard your group keeps rebuilding by hand, or someone has published a listing file you'd like to run, this is how it gets in.

!!! info "Where the trust comes from"
    You control the directory, so a file being in it *is* your decision to publish it. Every listing is shown with the publisher named in its own file, wherever it appears — on the card, on its page, and in the dialog where someone adds it — so the question of who made it is answered at the moment of the decision. Listings that ship with Initiative are credited to Initiative, and a listing you add can't claim that credit (see [Reserved names](#names-you-cant-use)).

## Turning it on

Set `MARKETPLACE_EXTRA_CATALOG_DIR` to a directory inside the container, and mount your own folder there:

```yaml
services:
  initiative:
    environment:
      MARKETPLACE_EXTRA_CATALOG_DIR: /app/marketplace-catalog
    volumes:
      - ./marketplace-catalog:/app/marketplace-catalog
```

Leave the variable unset — the default — and none of this happens: no directory is read and your marketplace shows the built-in listings only.

Initiative reads the directory **every time it starts**. Only `*.json` files are read, so a `README.md` or an image sitting alongside them is ignored rather than reported as a mistake.

## What a listing file looks like

One file per listing. Here's a complete dashboard listing:

```json
{
  "uid": "K7M2QX8N4TVB9C",
  "public_id": "acme.standup",
  "kind": "dashboard",
  "name": "Standup board",
  "author": {
    "name": "Acme Engineering",
    "url": "https://example.com/acme",
    "contact": "tools@example.com"
  },
  "description": "What everyone is on today.",
  "long_description": "A single screen for the morning standup: what's in flight, what's blocked, and how the week is tracking.",
  "avatar_url": "/marketplace/acme-standup.svg",
  "images": [],
  "version": "1.0.0",
  "release_notes": "First release.",
  "definition": {
    "schema_version": 1,
    "kind": "dashboard",
    "layout": { "columns": 12 },
    "widgets": [
      {
        "id": "w1",
        "type": "stat",
        "title": "Open tasks",
        "grid": { "x": 0, "y": 0, "w": 4, "h": 2 },
        "binding": { "source": "task_counts" }
      },
      {
        "id": "w2",
        "type": "gantt",
        "title": "This week",
        "grid": { "x": 4, "y": 0, "w": 8, "h": 6 },
        "binding": { "source": "tasks" }
      }
    ]
  }
}
```

| Field | Required | What it is |
|---|---|---|
| `uid` | ✅ | The listing's product code — see [Choosing a uid](#choosing-a-uid). |
| `public_id` | ✅ | A readable id, `<publisher>.<slug>`. Lowercase letters, digits, `.`, `-` and `_`. |
| `kind` | ✅ | `dashboard` or `app`. |
| `name` | ✅ | What the card is called. |
| `author` | ✅ | Who wrote it: `name` is required, `url` and `contact` are optional. |
| `description` | ✅ | The one-line blurb on the browse card. |
| `long_description` | | The longer text on the detail page. |
| `avatar_url` | ✅ | The listing's artwork — see [Artwork](#artwork). |
| `images` | | Screenshots for the detail page, same rules as `avatar_url`. |
| `version` | ✅ | The version this file publishes, e.g. `1.2.0`. |
| `release_notes` | | What changed, shown beside the version. |
| `min_app_version` | | The oldest Initiative this version runs on. Newer-than-you versions are shown as needing an update rather than hidden. |
| `definition` | ✅ | The body — what installing actually produces. |

Everything is checked before it's published, by the same validation the built-in listings go through. A file that doesn't pass is skipped with the reason recorded, and the listings around it publish normally.

### Attribution is required

**A listing states who wrote it, or it isn't published.** `author.name` is not optional, on any route into the catalog. People decide whether to install something based on who it's from, so the question is answered on the card, the detail page, and the install dialog — always next to where the listing came from, so a name never stands in for provenance.

### Names you can't use

`core.*` belongs to the listings Initiative ships. A file in your directory claiming a `core.` public id is refused, and named in the scan result, so an id can never imply an origin the listing doesn't have. Publish under your own prefix instead: an organization name, a domain, a team.

A uid or public id already published by another source — a built-in, or a registry your deployment follows — is also refused rather than quietly taken over. Two listings claiming the same identity is a mistake worth seeing.

## Choosing a uid

The `uid` is a product code, like a barcode. It identifies the *listing*, so "install `K7M2QX8N4TVB9C`" means the same thing on every Initiative carrying it — which is what makes a listing shareable at all.

- **14 characters**, from `0123456789ABCDEFGHJKMNPQRSTVWXYZ`. The letters `I`, `L`, `O` and `U` are deliberately absent so a code can be read aloud or copied by hand without confusion.
- **You assign it**, once, when you first publish. Generate 14 random characters from that set.
- **It never changes and is never reused.** Editing the listing keeps the uid; a genuinely different listing gets a new one.

## Artwork

`avatar_url` and `images` are **paths on your own Initiative**, not links to other sites — so no listing can pull in an image from somewhere else. Each must start with `/` and use only letters, digits, `/`, `.`, `-` and `_`.

Put the files where Initiative serves its static assets, under `marketplace/`:

```yaml
volumes:
  - ./marketplace-catalog:/app/marketplace-catalog
  - ./marketplace-art:/app/static/marketplace
```

A file at `./marketplace-art/acme-standup.svg` is then reachable at `/marketplace/acme-standup.svg`, which is what the manifest above names. SVG and PNG both work; square artwork looks best on the cards.

## Publishing an update

Edit the file and bump `version`:

- **A version is immutable once published.** Re-publishing the same version string with different content is refused — bump it instead. This is what lets a community pin a version and trust it stays what they installed.
- **The listing's name, blurbs and artwork are editable in place**, with no version bump. Fixing a typo in a description doesn't need a release.
- **Nothing is pushed into a community.** An installed dashboard keeps running the version it pinned; communities see an *update available* badge with your release notes and choose when to take it.

## Removing a listing

Delete the file. On the next scan the listing is **withdrawn**: it disappears from browse and can't be installed again.

Withdrawn isn't deleted. Communities that already installed it keep what they installed, working exactly as before, along with the record of where it came from — removing a listing from your catalog never reaches into a community and takes something away. Put the file back and the listing is published again.

A file that's *present but broken* is not a removal: it still claims its listing, so a manifest you're in the middle of editing leaves the existing listing alone rather than pulling it while you work.

## Picking up changes without a restart

Restarting Initiative rescans the directory. To pick up a change immediately, the [owner](platform-roles.md) can trigger a rescan on demand:

```bash
curl -X POST https://your-initiative.example.com/api/v1/marketplace/operator-catalog/rescan \
  -H "Authorization: Bearer $TOKEN"
```

The response says what happened, and names any file it skipped:

```json
{
  "published": 3,
  "withdrawn": 1,
  "skipped": 1,
  "problems": [
    { "file": "draft.json", "reason": "draft.json is not valid JSON: Expecting ',' delimiter: line 9 column 3" }
  ]
}
```

Only one scan runs at a time; a second request while one is in flight is refused rather than queued.

## When something doesn't appear

Work down this list — the scan result above answers most of it directly.

| What you see | What it usually means |
|---|---|
| Nothing at all published | The directory isn't mounted where `MARKETPLACE_EXTRA_CATALOG_DIR` points. A rescan says so explicitly. |
| One file missing, the rest fine | That file was skipped. Its name and the reason are in the scan result and the server log. |
| "reserved" in the reason | The `public_id` starts with `core.` — publish under your own prefix. |
| "already published by the builtin catalog" | The `uid` or `public_id` belongs to another listing. Pick a new uid. |
| A listing appears but can't be installed | Its `min_app_version` is newer than this Initiative, or a community already has it. |
| An app listing never appears on the Apps shelf | An app is served by a program you run, and this server offers one only where that app service is registered and switched on. Register it (or switch it back on) and the listing appears. Dashboards need nothing of the sort. |
| Artwork is a broken image | The file isn't under the static `marketplace/` directory, or the path in the manifest doesn't match its name. |

## Related

- [Configuration](configuration.md) — every setting, including `MARKETPLACE_EXTRA_CATALOG_DIR`.
- [Platform roles](platform-roles.md) — who may trigger a rescan.
- [Apps & the marketplace](../guides/apps-and-marketplace.md) — how your listings look to the people installing them.
- [Tools](../guides/tools.md) — what a dashboard is, from a member's side.
