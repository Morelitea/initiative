# Security alerts: destination, thresholds, and what to do

Initiative records security-relevant events in `audit_events` and logs them.
This runbook covers the third thing: getting a person's attention when one of
them crosses a threshold.

## Configuring a destination

```
SECURITY_ALERT_WEBHOOK_URL=https://hooks.example.com/services/...
```

One HTTPS POST per alert. The body is JSON carrying a `text` field, which is
what Slack, Discord, Mattermost and Teams incoming webhooks render, alongside
`kind`, `summary`, `detail` and `at` for anything that parses instead.
Choosing a shape several destinations accept is what keeps this from being a
choice of vendor.

**Unset is a supported configuration and it is the default.** Warnings are
still logged; nothing is delivered. No deployment has to set this to keep
working — which is also why setting it is easy to forget, hence the test below.

The URL is resolved and pinned through the same egress guard as every other
outbound request (`app/services/safe_http.py`). A private address is allowed
here, because an in-cluster relay is a legitimate destination for something an
operator configured.

## Prove it works before you need it

```
python -m app.services.platform.security_alerts
```

Exit `0` delivered, `1` the destination refused it, `2` no destination is
configured. Run it when you set the URL, and again after changing it. A
destination nobody has seen deliver is a destination nobody knows is broken,
and an incident is the wrong time to find out.

## Thresholds

| Setting | Default | What it means |
| --- | --- | --- |
| `SECURITY_ALERT_FAILED_SIGN_IN_THRESHOLD` | `10` | Refused sign-ins against **one account** before alerting. `0` disables the rule and leaves the destination working. |
| `SECURITY_ALERT_FAILED_SIGN_IN_WINDOW_MINUTES` | `15` | The window those failures are counted over. |

A single refused sign-in is somebody mistyping their password and belongs in
the audit log and nowhere else. The alert fires **on the crossing only**, not
on every failure past it: an attacker who keeps going would otherwise send one
alert per attempt, which is how a destination gets muted and the next real
alert is missed.

The alert names the **account id**, never the address that was typed. An
address submitted to a sign-in form is the one part of a refusal that may
belong to nobody.

## Responding to `auth.failed_sign_in_threshold`

1. **Find the account.** `detail.user_id` is an Initiative user id. The
   matching `audit_events` rows carry the reasons (`bad_password`,
   `inactive`, `email_unverified`), which separate a forgotten password from a
   guess.
2. **Check whether any succeeded.** An `auth.signed_in` for the same account
   after the failures is the difference between an attempt and an entry.
3. **If it looks like an entry**, change the account's password — which
   revokes its sessions — and review what that account did afterwards.
4. **If it looks like a forgotten password**, nothing needs doing. Repeated
   alerts for the same person are a signal the threshold is too low for this
   deployment, not that something is wrong.

Rate limiting on the sign-in endpoint is a separate, preventive control and it
keeps working whether or not any of this is configured.

## Retiring an alert

Alerts are stateless — nothing is stored, acknowledged, or re-sent. To stop a
rule, set its threshold to `0`; to stop everything, unset
`SECURITY_ALERT_WEBHOOK_URL`. Both leave the audit log and the application log
untouched, which is the floor this never drops below.
