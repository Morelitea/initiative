---
icon: lucide/split
---

# Self-host or let us host it

Initiative comes two ways. It's the same software and the same protections either way — the difference is mostly about who gets up at 2am when the disk fills.

<div class="grid cards" markdown>

-   :material-server: __Host it yourself__

    Free, open source, and the whole thing. Runs happily on a spare mini PC, a NAS, or a cheap cloud box.

    [:octicons-arrow-right-24: Installation guide](admin/installation.md)

-   :material-cloud-outline: __Let us host it__ · *coming soon*

    A paid service. You sign up, you're in, and the server becomes our problem.

</div>

## What's the same

Initiative itself, entirely. There's no "community edition" here with the good bits filed off.

- **Every feature in the app.** Projects, documents, whiteboards, the calendar, queues, counters, dashboards, tags, the marketplace, encrypted messages. All of it, both ways.
- **Every protection.** The same isolation between groups, the same access model, the same end-to-end encryption on direct messages.
- **Your data stays yours either way.** Export it, delete it, take it somewhere else. See [Data & compliance](security/data-and-compliance.md).

Nothing in Initiative is held back to make the hosted version look better. What the hosted service adds is a couple of **separate services running alongside it** — described below — rather than features carved out of the app you'd otherwise have.

## What's different

| | **You host it** | **We host it** |
|---|---|---|
| Cost | Free (you pay for the machine) | Paid subscription |
| Setup | Docker Compose, about ten minutes | Sign up |
| Updates, backups, uptime | Yours | Ours |
| Where your data lives | Wherever you put it | Where our service runs |
| Who you ask when it breaks | You, and the community | Us |
| Version you're on | Whichever you pull | The current one |
| Apps that need a service behind them | You run the service | Already running |
| Automations | — | Available, metered separately |

### Apps that need something running behind them

Some [marketplace apps](guides/apps-and-marketplace.md#adding-an-app) aren't just a screen. They need a program running alongside Initiative to do their actual job — an app that talks to another service has to be somewhere that can hold the conversation, which is more than a web page can manage on its own.

On a server you run, those apps work once you've stood that program up yourself. On the hosted service it's already running. Two we're launching with:

**GitHub integration.** Connect a repository so the work in Initiative and the work in your codebase stop being two separate stories that somebody has to reconcile by hand.

This one is **open source like the rest of Initiative**. If you run infrastructure and fancy standing it up yourself, nothing is stopping you and we'd genuinely like to see it. Being straight with you though: it's a real deployment rather than a config flag — a separate service with its own moving parts, and more than most people want sitting on top of a `docker compose up`.

**Automations.** Rules that do the repetitive bit for you, so nobody has to remember to move the card every Friday. This one runs only on the hosted service, and it's priced separately from the subscription.

Here's why, because you deserve the actual reason: automations aren't a screen we drew once. They're something that has to be *running and listening* the entire time your rules exist, which costs us continuously — in the same unglamorous way storage does — and goes up the more you use it. Charging separately is us passing along a real running cost rather than gating a feature to make a cheaper plan look thin. We'd rather say that here than have you discover it at checkout.

More will follow, of both kinds.

## Which one is you?

**Host it yourself if** you already run things — a NAS, a homelab, a couple of containers — or if where the data physically sits is something you have to answer for. Data residency stops being a negotiation when you're the one picking the datacentre.

**Let us host it if** you'd rather spend your evening on the actual work. A club treasurer, a small business owner, a PTA chair — none of you signed up to learn what a database is, and you shouldn't have to. It's also the only route to automations, and much the shortest one to the GitHub integration.

You can start on one and move to the other, too. Same software, and the export formats are ordinary files rather than something only we can open.

!!! info "The hosted service isn't open yet"
    It's coming. Until then, self-hosting is the way in — and it's a genuinely good way in, not a consolation prize. Plenty of groups will never want anything else. Start with the [installation guide](admin/installation.md).

## Related

- [Installation](admin/installation.md) — get a server running.
- [Data & compliance](security/data-and-compliance.md) — ownership, residency, and what a court could actually be handed.
- [Backups & updates](admin/backups-and-updates.md) — the two jobs that are yours if you self-host.
