---
icon: lucide/fingerprint
---

# Passkeys

A passkey is a sign-in with nothing to type. Your phone, your laptop or your password manager holds a key; the site asks it a question; you prove it's you with the fingerprint, face or PIN you already unlock the device with; done. No password, no code from an app, nothing to remember and nothing to spell wrong at eleven at night.

## Adding one

1. **User settings → Security → Passkeys → Add a passkey**.
2. Give it a name you'll recognise in a list — *Laptop*, *Phone*, *The blue key on the lanyard*.
3. Confirm your password.
4. Your browser takes over from here: it asks where to keep the key and how you'd like to prove it's you. Say yes to whatever you normally unlock with.

That's it. It's in the list, with the date you added it.

Where the key ends up is your browser's decision, not ours. Signed in to a password manager or the phone's own keychain? It probably goes there, and shows up as **Synced** in the list — meaning the same key is now on your other devices too, and losing this one doesn't lose it. Not synced? It lives on that device and nowhere else, so add another for the next one. You can have twenty.

## Signing in with it

On the sign-in screen, press **Sign in with a passkey**, or just click into the email box — most browsers offer your passkeys right there, above the addresses they've remembered. Prove it's you, and you're in.

On the phone app, the button opens your browser for a moment, because that's where your passkeys live, and hands you straight back once you've unlocked one. The app's own session doesn't carry that unlock with it, so a community that asks for a code from your authenticator app will still ask the app for one.

## When a device goes

Remove its passkey: **User settings → Security → Passkeys**, the bin next to the name, and your password to confirm. Sign in with your password or another passkey first if you need to. Nothing on the lost device can add one back.

Not sure which one was the lost phone? The list says when each was last used. The one that stopped is the one that went.

??? techspec "The details"
    WebAuthn, through the reference libraries on both sides. Credentials are made as discoverable, so a sign-in can start from the key rather than from a typed address, and every ceremony requires user verification: a passkey that cannot prove the person as well as the device is not one this site will register or accept.

    The relying party is the host of the deployment's own address, and the origin must match it exactly. Each credential records the host it was made under, so a deployment that moves to a new address refuses its old passkeys and records a plain reason in the audit log rather than a signature that does not verify. A sign-in through a passkey is recorded as a multi-factor cryptographic authenticator — `hwk` for a device-bound key, `swk` for a synced one, and `mfa` — which is what a community requiring a second factor reads.

    Public keys only are stored, alongside the authenticator's counter, which must never go backwards. No attestation is requested or kept.
