"""Changes that give a deployment's older clients time to catch up.

When a release changes something an installed client depends on, the old way
keeps working for a grace period and then stops. The clock is the deployment's
own: it starts the first time this deployment boots with the change (recorded
in ``app_settings.transitions``), so a deployment that skips releases still
gives its clients the whole window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Transition:
    name: str
    grace: timedelta


#: App bundles from before the native sign-in code flow are handed a device
#: token; after this they are asked to update.
NATIVE_SIGN_IN_CODE = Transition("native_sign_in_code", timedelta(days=60))

#: Devices registered before their keys were signed sign themselves the next
#: time they open. After this, an unsigned registration is refused.
DM_SIGNED_DEVICES = Transition("dm_signed_devices", timedelta(days=30))

TRANSITIONS: tuple[Transition, ...] = (NATIVE_SIGN_IN_CODE, DM_SIGNED_DEVICES)
