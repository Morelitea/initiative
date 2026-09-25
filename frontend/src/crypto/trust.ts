/**
 * Which of another person's devices this browser will encrypt to. Every path
 * that addresses another person reads the directory through here.
 */

import { readDirectoryApiV1UsersUserIdDmDevicesGet as readDirectory } from "@/api/generated/direct-messages/direct-messages";
import type { DmSessionKey } from "@/api/generated/initiativeAPI.schemas";

import { type PeerKeyChange, peerDeviceKeys, peerKeyChanges, sessionForDevice } from "./store";

/**
 * One person's devices that may be addressed, and how many were held back, so a
 * send left with nothing to address can say which of the two reasons it was.
 */
export interface PeerDirectory {
  devices: DmSessionKey[];
  withheld: number;
}

/**
 * Read the other party's devices, and notice when one's key has changed.
 *
 * A changed or newly introduced device is withheld from this send until the
 * change is acknowledged, so nothing is encrypted to a key the person has not
 * seen. Unchanged devices still receive the message.
 */
export async function readPeerDirectory(otherUserId: number): Promise<PeerDirectory> {
  const theirs = await readDirectory(otherUserId);
  const seen = await Promise.all(
    theirs.devices.map(async (device) => ({
      deviceId: device.device_id,
      fingerprint: device.fingerprint_key,
      identityKey: device.identity_key,
      previouslyAddressed: (await sessionForDevice.get(device.device_id)) !== undefined,
    }))
  );
  const changes = await peerDeviceKeys.reconcile(otherUserId, seen);
  if (changes.length > 0) {
    // The hold is already recorded -- `reconcile` writes it in the same
    // transaction that records the key, so no send can see one without the
    // other. Not repeated here: two places writing the same fact is how they
    // come to disagree.
    //
    // This is the rest of it. The session in hand was negotiated with the key
    // that has just been replaced, so the far end cannot read anything sent
    // through it. Drop the pointer and the next send opens a fresh one against
    // the key the directory now returns. Safe to do after the hold rather than
    // with it: a held device is not addressable, so nothing reaches for the
    // session in between.
    await Promise.all(changes.map((change) => sessionForDevice.forget(change.deviceId)));
  }

  // Keep the key out of every retry, not only the send that first noticed it.
  // Acknowledgement means the person has completed the out-of-band check and
  // deliberately allows future messages to use that device.
  const unverified = new Set(
    (await peerKeyChanges.all())
      .filter((change) => change.userId === otherUserId)
      .map((change) => change.deviceId)
  );
  const addressable = theirs.devices.filter((device) => !unverified.has(device.device_id));
  return { devices: addressable, withheld: theirs.devices.length - addressable.length };
}

/**
 * Device keys that changed under a conversation this browser was already in.
 *
 * Newest first: if several have accrued, the one that just happened is the one
 * the person is reacting to.
 */
export async function peerKeyChangesWaiting(): Promise<PeerKeyChange[]> {
  const changes = await peerKeyChanges.all();
  return [...changes].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}
