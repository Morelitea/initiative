---
icon: lucide/shield-check
---

# Two-factor authentication

A password is one thing you know. Two-factor authentication adds one thing you have: a six-digit code from an app on your phone, changing every thirty seconds, asked for after your password.

It takes about two minutes to set up and it is the single biggest improvement you can make to the security of your account.

## What you need

An authenticator app. Google Authenticator, Microsoft Authenticator, Authy, 1Password, Bitwarden, Ente Auth — any of them, they all do the same standard thing. If you already use one for your bank or your email, use that one.

## Turning it on

1. **User settings → Security → Two-factor authentication → Set up**.
2. Confirm your password.
3. Scan the square with your authenticator app. Can't scan — desktop app, cracked camera, phone at the bottom of a bag? There's a key underneath the code you can type in instead.
4. Type the six digits your app is now showing.

That's it. It's on.

!!! warning "Then save your recovery codes"
    The moment it's on you'll be shown ten **recovery codes**. These are the only way back into your account if your phone is lost, broken, or wiped.

    Save them somewhere that is not your phone. A password manager, a text file on your laptop, a piece of actual paper in an actual drawer. Somewhere you would still have access to if the phone went into a canal.

    You will not be shown them again.

## Signing in from now on

Your password, then your code. Same as before with one extra step.

Signing in on your phone works the same way — the app asks for the code too, which is the point: a second factor that only guards one door isn't guarding much.

## When you don't have your phone

Use a recovery code instead. On the code screen, choose **Use a recovery code** and enter one of the ten.

Each code works exactly once. The Security page shows how many you have left, and tells you off when you're running low. **New recovery codes** replaces the whole set with a fresh ten — do that if you've used a few, or if you've ever been unsure where the old list ended up.

## If your phone is gone and so are the codes

Ask whoever runs your Initiative. They can clear the second factor from your account so you can sign in with your password and set it up again on your new phone.

They can only *remove* it. Nobody, at any level, can see your key or your recovery codes — there's nothing to look up.

## Turning it off

**User settings → Security → Turn off**. You'll need your password and one more code — either from your app or a recovery code.

Turning it off discards your recovery codes and signs you out everywhere else, which is deliberate: if you're turning this off because something went wrong, every other session going with it is the useful part.

??? techspec "The details"
    Standard TOTP, RFC 6238: SHA-1, six digits, thirty-second steps, which is what every authenticator app expects. Codes one step either side of the current one are accepted, so a phone clock that has drifted slightly still works.

    Each code is accepted once. Presenting the same code twice — even inside its thirty seconds — gets you in once, which is why signing in immediately after setup may mean waiting for the next code.

    Recovery codes are stored only as hashes, and your key is encrypted at rest. Neither is readable by anybody, including whoever administers the site.
