/**
 * This browser's device: registering it, keeping its prekeys topped up, and
 * taking it away again.
 */

import {
  listConversationsApiV1MeDmConversationsGet as listConversations,
  listDevicesApiV1MeDmDevicesGet as listDevices,
  registerDeviceApiV1MeDmDevicesPost as registerDevice,
  removeDeviceApiV1MeDmDevicesDeviceIdDelete as removeDevice,
  signDeviceApiV1MeDmDevicesDeviceIdSignaturePut as signDevice,
  topUpKeysApiV1MeDmOneTimeKeysPost as topUpKeys,
} from "@/api/generated/direct-messages/direct-messages";
import type { DmConversationRead, DmDeviceRead } from "@/api/generated/initiativeAPI.schemas";
import { readUsersMeApiV1UsersMeGet as readMe } from "@/api/generated/users/users";

import { ratchet, stopRatchet } from "./client";
import type { CodeKeys } from "./safetyCode";
import { withAccount } from "./sessions";
import {
  deviceClaim,
  deviceOwner,
  forgetDevice,
  historyAsk,
  messageLog,
  deviceId as storedDeviceId,
} from "./store";
import { ingestDirectory, type PeerDirectory, readPeerDirectory } from "./trust";

/** How many prekeys a device keeps published. */
const KEY_POOL = 50;

/** Below this many unclaimed prekeys, the pool is topped back up to `KEY_POOL`. */
const KEY_LOW_WATER = 15;

/**
 * What one run of work reads once and every step inside it shares.
 *
 * A collection builds one and hands it to everything it does, so one
 * collection reads the account's devices, the conversation list and each
 * member's directory once; a message somebody sends builds its own. `device`
 * is this browser's, `self` the account it belongs to, and `own` the account's
 * devices through the trust seam, this one included.
 */
export interface Context {
  self: number;
  device: string;
  own: PeerDirectory;
  conversations: () => Promise<DmConversationRead[]>;
  /** A directory that cannot be read reads as nobody there, for that member only. */
  directory: (userId: number) => Promise<PeerDirectory>;
}

async function contextFor(self: number, device: string, listed: DmDeviceRead[]): Promise<Context> {
  let conversations: Promise<DmConversationRead[]> | undefined;
  const directories = new Map<number, Promise<PeerDirectory>>();
  return {
    self,
    device,
    own: await ingestDirectory(
      self,
      listed.map(({ id, ...entry }) => ({ ...entry, device_id: id }))
    ),
    conversations: () =>
      (conversations ??= listConversations().then((response) => response.conversations)),
    directory: (userId) => {
      if (!directories.has(userId)) {
        directories.set(
          userId,
          readPeerDirectory(userId).catch(() => ({ devices: [], held: [] }))
        );
      }
      return directories.get(userId) as Promise<PeerDirectory>;
    },
  };
}

/** The account this browser's device belongs to, asked of the server once. */
async function owner(): Promise<number> {
  const stored = await deviceOwner.get();
  if (stored !== undefined) return stored;
  const { id } = await readMe();
  await deviceOwner.set(id);
  return id;
}

/**
 * Publish more prekeys when the pool is running down.
 *
 * A device publishes a pool of single-use keys and one reusable fallback. Each
 * new session someone opens spends one from the pool; once it is empty the
 * fallback answers every time instead, and a key used twice is a weaker start
 * than a key used once. Only the client can refill it — the server has never
 * held a private half.
 */
async function replenish(deviceId: string, held: number): Promise<void> {
  if (held >= KEY_LOW_WATER) return;
  try {
    const minted = await withAccount(async (pickle) => {
      const keys = await ratchet.generateKeys(pickle, KEY_POOL - held, false);
      return { next: keys.pickle, value: keys.one_time_keys };
    });
    if (minted === null || minted.length === 0) return;
    // The account is written before the keys are published, never after: a
    // public key whose private half was dropped is one a sender can claim and
    // this device can never answer.
    await topUpKeys({ device_id: deviceId, one_time_keys: minted });
  } catch {
    // The fallback key still answers, and the next visit tries again.
  }
}

/**
 * Sign a device registered before signing, and replace the keys it published
 * with signed ones. The server takes this once; a device it refuses, or a
 * request that fails, is tried again on the next visit.
 */
async function signItself(self: number, device: string): Promise<DmDeviceRead[] | null> {
  try {
    const signed = await withAccount(async (pickle) => {
      const keys = await ratchet.generateKeys(pickle, KEY_POOL, true);
      const signature = await ratchet.signDevice(keys.pickle, self);
      return { next: keys.pickle, value: { keys, signature } };
    });
    if (signed === null || signed.keys.fallback_key === null) return null;
    // The account is written before the keys are published, as a top-up is.
    const response = await signDevice(device, {
      signature: signed.signature,
      fallback_key: signed.keys.fallback_key,
      one_time_keys: signed.keys.one_time_keys,
    });
    return response.devices;
  } catch {
    return null;
  }
}

/**
 * This browser's device, and the account's other devices alongside it.
 *
 * The two are read together because every caller needs both, and the device
 * list is what proves this browser's own registration is still good.
 */
export async function ensureDeviceContext(): Promise<Context> {
  const existing = await storedDeviceId.get();
  if (existing) {
    // A device the server no longer knows about — revoked from another tab, or
    // the account erased — has to be registered again rather than used.
    const devices = (await listDevices()).devices;
    const known = devices.find((device) => device.id === existing);
    if (known) {
      const self = await owner();
      if (!known.signature) {
        return contextFor(self, existing, (await signItself(self, existing)) ?? devices);
      }
      await replenish(existing, known.one_time_key_count);
      return contextFor(self, existing, devices);
    }
    // The dead device is named, so only a claim still recording it reopens: a
    // second tab reaching the same conclusion waits for the first instead.
    await deviceClaim.invalidate(existing);
  }

  // Registration is a network round trip, so it cannot sit inside one database
  // transaction. Only one tab takes it; the rest wait for the answer. Two tabs
  // each registering would leave the server holding two devices and this
  // browser holding one set of private keys, and whatever was sent to the other
  // would never be readable.
  const turn = await deviceClaim.take();
  if (turn === null) {
    const id = await waitForRegistration(existing);
    return contextFor(await owner(), id, (await listDevices()).devices);
  }

  try {
    // Asked afresh: a new registration may be a different account signing in.
    const { id: self } = await readMe();
    await deviceOwner.set(self);
    const account = await ratchet.createAccount();
    const keys = await ratchet.generateKeys(account.pickle, KEY_POOL, true);
    if (keys.fallback_key === null) {
      throw new Error("the ratchet published no fallback key");
    }
    const response = await registerDevice({
      identity_key: account.identity_key,
      fingerprint_key: account.fingerprint_key,
      signature: await ratchet.signDevice(keys.pickle, self),
      fallback_key: keys.fallback_key,
      one_time_keys: keys.one_time_keys,
    });
    const created = response.device_id;
    if (!created) throw new Error("the server named no device");
    // The keys, the id and the claim in one write, and only while this is
    // still this tab's turn.
    if (!(await deviceClaim.settle(turn, created, keys.pickle))) {
      // Registration outran the claim and another tab took over. Its device is
      // the one this browser holds keys for, so the one just registered is
      // withdrawn rather than left collecting messages nothing can open.
      await removeDevice(created).catch(() => undefined);
      const id = await waitForRegistration(existing);
      return contextFor(self, id, (await listDevices()).devices);
    }
    // Whether this device may ask the account for its history is settled here,
    // on the one fact that can settle it: what this browser held at the moment
    // the device came into being. Worked out later — from a log that has since
    // collected a message or two — it cannot tell a device that arrived with
    // nothing from one that has everything, and a first attempt that failed
    // would never get a second.
    if (await messageLog.holdsAnything()) {
      await historyAsk.close();
    } else {
      await historyAsk.eligible();
    }
    return contextFor(self, created, response.devices);
  } catch (error) {
    // Hand the turn back, or the next attempt waits out the stale window for
    // a tab that has already given up.
    await deviceClaim.release(turn);
    throw error;
  }
}

/**
 * The id of this browser's device, registering it the first time.
 *
 * Registration publishes only public keys. The private halves stay inside the
 * account pickle, which never leaves this device.
 */
export async function ensureDevice(): Promise<string> {
  return (await ensureDeviceContext()).device;
}

/** Whether this browser has already been set up, without setting it up. */
export async function registeredDevice(): Promise<string | undefined> {
  return storedDeviceId.get();
}

/** This browser's device keys and account, for showing its code; `null` where it is not set up. */
export async function thisDevice(): Promise<({ userId: number } & CodeKeys) | null> {
  if (!(await storedDeviceId.get())) return null;
  const ctx = await ensureDeviceContext();
  const me = ctx.own.devices.find((device) => device.id === ctx.device);
  return me
    ? { userId: ctx.self, fingerprintKey: me.fingerprintKey, identityKey: me.identityKey }
    : null;
}

/**
 * Wait for whichever tab is registering to finish, then use what it made.
 *
 * `stale` is the device this tab already found gone from the server, if any:
 * an answer naming it is the settled claim that is being replaced, not the
 * replacement, so it is waited past.
 */
async function waitForRegistration(stale?: string): Promise<string> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const claim = await deviceClaim.read();
    if (claim?.status === "ready" && claim.deviceId !== stale) {
      const id = await storedDeviceId.get();
      if (id) return id;
    }
    if (claim?.status === "claiming" && claim.at === 0) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("another tab is still setting up encrypted messages");
}

/**
 * Leave nothing behind on this browser, and stop messages being addressed to it.
 *
 * What signing out calls. A decrypted conversation must not outlive the session
 * that read it — a shared computer is the whole reason — and a device whose
 * keys are gone should not go on being sent to: withdrawing it releases
 * everything the server was holding for it.
 *
 * The worker goes last. It keeps the pickle key it unwrapped, and stopping it
 * after the store is cleared means nothing read from the old store is still
 * held once this returns.
 */
export async function forgetMessagesOnThisDevice(): Promise<void> {
  const existing = await storedDeviceId.get();
  if (existing) {
    // Best effort: the local store is cleared either way, and a device left
    // behind is withdrawn the next time this browser registers.
    await removeDevice(existing).catch(() => undefined);
  }
  await forgetDevice();
  stopRatchet();
}
