/**
 * Direct messages, from the client's side.
 *
 * This is the orchestration the page uses: make sure this browser has a device,
 * open sessions with the other party's devices, encrypt once per destination,
 * and collect what has arrived. It is deliberately not React — the ratchet has
 * to advance in a defined order, and a hook re-running is not that.
 *
 * The client is the archive. A collected message is deleted from the server, so
 * what is written to the local log is the only copy this device will have.
 */

import {
  acknowledgeQueueApiV1MeDmQueueAckPost as ackQueue,
  claimOwnSessionKeysApiV1MeDmSessionKeysPost as claimOwnSessionKeys,
  claimSessionKeysApiV1UsersUserIdDmSessionKeysPost as claimSessionKeys,
  collectQueueApiV1MeDmQueueGet as collectQueue,
  listConversationsApiV1MeDmConversationsGet as listConversations,
  listDevicesApiV1MeDmDevicesGet as listDevices,
  readDirectoryApiV1UsersUserIdDmDevicesGet as readDirectory,
  registerDeviceApiV1MeDmDevicesPost as registerDevice,
  sendMessagesApiV1MeDmConversationsConversationIdMessagesPost as sendMessages,
  topUpKeysApiV1MeDmOneTimeKeysPost as topUpKeys,
} from "@/api/generated/direct-messages/direct-messages";
import type { DmDeviceRead } from "@/api/generated/initiativeAPI.schemas";

import { ratchet } from "./client";
import {
  accountPickle,
  deviceClaim,
  messageLog,
  type SessionOrigin,
  type StoredMessage,
  sessionForDevice,
  sessionOrigin,
  sessionPickle,
  sessionsInConversation,
  deviceId as storedDeviceId,
} from "./store";

/** How many prekeys a device keeps published. */
const KEY_POOL = 50;

/** Below this many unclaimed prekeys, the pool is topped back up to `KEY_POOL`. */
const KEY_LOW_WATER = 15;

/** How many times a write to the account is retried when another tab moves it. */
const ACCOUNT_ATTEMPTS = 3;

/**
 * Nobody on the other side has set up encrypted messaging yet.
 *
 * Distinct from a failed send: there is no device to address, so there is
 * nothing to queue and no later moment at which this message would arrive.
 */
export class RecipientHasNoDeviceError extends Error {
  constructor() {
    super("that account has no device that can receive encrypted messages");
    this.name = "RecipientHasNoDeviceError";
  }
}

/** One destination for a message: a device, and whose it is. */
interface Destination {
  id: string;
  identityKey: string;
  origin: SessionOrigin;
}

/**
 * Advance the account, and only keep the result if nobody else moved it first.
 *
 * The account holds the private half of every prekey it has published, and more
 * than one thing advances it: collecting a pre-key message spends a key,
 * topping the pool up mints fifty. Two tabs starting from the same pickle each
 * write a different account, and the loser's published keys lose their private
 * halves — so a writer that loses redoes its work against what is stored.
 *
 * `work` returns `null` for "there is nothing I can do with this account", and
 * so does this: a caller that never gets its turn treats it the same way.
 */
async function withAccount<T>(
  work: (pickle: string) => Promise<{ next: string; value: T } | null>
): Promise<T | null> {
  for (let attempt = 0; attempt < ACCOUNT_ATTEMPTS; attempt += 1) {
    const current = await accountPickle.get();
    if (!current) throw new Error("this device has no key store");
    const done = await work(current);
    if (done === null) return null;
    if (await accountPickle.swap(current, done.next)) return done.value;
  }
  return null;
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
 * This browser's device, and the account's other devices alongside it.
 *
 * The two are read together because every caller needs both, and the device
 * list is what proves this browser's own registration is still good.
 */
async function ensureDeviceContext(): Promise<{ id: string; devices: DmDeviceRead[] }> {
  const existing = await storedDeviceId.get();
  if (existing) {
    // A device the server no longer knows about — revoked from another tab, or
    // the account erased — has to be registered again rather than used.
    const devices = (await listDevices()).devices;
    const known = devices.find((device) => device.id === existing);
    if (known) {
      await replenish(existing, known.one_time_key_count);
      return { id: existing, devices };
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
  if (!(await deviceClaim.take())) {
    const id = await waitForRegistration(existing);
    return { id, devices: (await listDevices()).devices };
  }

  try {
    const account = await ratchet.createAccount();
    const keys = await ratchet.generateKeys(account.pickle, KEY_POOL, true);
    if (keys.fallback_key === null) {
      throw new Error("the ratchet published no fallback key");
    }
    const response = await registerDevice({
      identity_key: account.identity_key,
      fingerprint_key: account.fingerprint_key,
      fallback_key: keys.fallback_key,
      one_time_keys: keys.one_time_keys,
    });
    const created = response.devices[response.devices.length - 1];
    // Keys first, then the id, then the claim: a tab that sees the claim
    // settled must find everything the id refers to already written.
    await accountPickle.set(keys.pickle);
    await storedDeviceId.set(created.id);
    await deviceClaim.settle(created.id);
    return { id: created.id, devices: response.devices };
  } catch (error) {
    // Hand the claim back, or the next attempt waits out the stale window for
    // a tab that has already given up.
    await deviceClaim.release();
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
  return (await ensureDeviceContext()).id;
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

/** The session already held with a device, if it is still usable. */
async function establishedSession(deviceId: string): Promise<string | null> {
  const known = await sessionForDevice.get(deviceId);
  if (!known) return null;
  return (await sessionPickle.get(known)) ? known : null;
}

async function openOutboundSession(
  conversationId: string,
  destination: Destination,
  oneTimeKey: string
): Promise<string> {
  const account = await accountPickle.get();
  if (!account) throw new Error("this device has no key store");
  const session = await ratchet.createOutboundSession(account, destination.identityKey, oneTimeKey);
  await sessionPickle.set(session.session_id, session.session_pickle);
  await sessionOrigin.set(session.session_id, destination.origin);
  await sessionForDevice.set(destination.id, session.session_id);
  await sessionsInConversation.add(conversationId, session.session_id);
  return session.session_id;
}

/**
 * Claim one prekey from each device that still needs a session opened with it.
 *
 * Claiming spends a key, so it is asked for only where there is nothing to
 * carry the message yet. An established conversation therefore costs neither
 * side a prekey, however many messages it carries.
 */
async function claimKeysFor(
  missing: Destination[],
  otherUserId: number,
  ownDeviceId: string
): Promise<Map<string, string>> {
  const keys = new Map<string, string>();
  const claims = [];
  if (missing.some((destination) => destination.origin === "other")) {
    claims.push(claimSessionKeys(otherUserId));
  }
  if (missing.some((destination) => destination.origin === "self")) {
    claims.push(claimOwnSessionKeys({ device_id: ownDeviceId }));
  }
  for (const claim of await Promise.all(claims)) {
    for (const device of claim.devices) {
      if (device.one_time_key) keys.set(device.device_id, device.one_time_key.public_key);
    }
  }
  return keys;
}

/**
 * Encrypt one message for every device that should see it and hand the
 * ciphertext to the server.
 *
 * "Every device" is the other party's *and* this account's others, so their
 * own tabs render their outbox. The server never sees the two as different.
 */
export async function sendText(
  conversationId: string,
  otherUserId: number,
  body: string
): Promise<StoredMessage> {
  const { id: mine, devices: ourDevices } = await ensureDeviceContext();

  // The directory rather than a claim: reading it spends nothing, and most
  // messages go to devices this one already has a session with.
  const theirs = await readDirectory(otherUserId);
  if (theirs.devices.length === 0) {
    // Nothing to address and nothing to queue against. Saying so beats writing
    // the message into a thread it would never leave.
    throw new RecipientHasNoDeviceError();
  }

  const destinations: Destination[] = [
    ...theirs.devices.map((device) => ({
      id: device.device_id,
      identityKey: device.identity_key,
      origin: "other" as const,
    })),
    ...ourDevices
      .filter((device) => device.id !== mine)
      .map((device) => ({
        id: device.id,
        identityKey: device.identity_key,
        origin: "self" as const,
      })),
  ];

  const held = new Map<string, string | null>();
  for (const destination of destinations) {
    held.set(destination.id, await establishedSession(destination.id));
  }
  const missing = destinations.filter((destination) => !held.get(destination.id));
  const claimed =
    missing.length > 0 ? await claimKeysFor(missing, otherUserId, mine) : new Map<string, string>();

  const messages = [];
  let reachedThem = false;
  for (const destination of destinations) {
    let sessionId = held.get(destination.id) ?? null;
    if (!sessionId) {
      const oneTime = claimed.get(destination.id);
      if (!oneTime) {
        // A device that published nothing we can open a session with. Skipping
        // beats sending it something it cannot read.
        continue;
      }
      sessionId = await openOutboundSession(conversationId, destination, oneTime);
    }
    const pickle = await sessionPickle.get(sessionId);
    if (!pickle) continue;
    const encrypted = await ratchet.encrypt(pickle, body);
    await sessionPickle.set(sessionId, encrypted.session_pickle);
    if (destination.origin === "other") reachedThem = true;
    messages.push({
      recipient_device_id: destination.id,
      message_type: encrypted.message_type,
      payload: encrypted.ciphertext,
    });
  }

  // Their devices are all there was to address and none of them could be
  // opened. Nothing is sent, here or later, so the thread should not show a
  // message as though something had been.
  if (!reachedThem) throw new RecipientHasNoDeviceError();

  await sendMessages(conversationId, { messages });

  const stored: StoredMessage = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    body,
    at: new Date().toISOString(),
    mine: true,
  };
  await messageLog.append(conversationId, stored);
  return stored;
}

/**
 * The identity keys a pre-key message in each conversation could have come from.
 *
 * Only conversations that actually have one are looked up: reading a directory
 * is a request per conversation, and an ordinary message names its session
 * without needing any of this.
 */
async function identitiesForPreKeys(
  conversationIds: Set<string>,
  ourDevices: DmDeviceRead[]
): Promise<Map<string, Destination[]>> {
  const candidates = new Map<string, Destination[]>();
  if (conversationIds.size === 0) return candidates;

  // This account's own devices are tried in every conversation: a pre-key
  // message anywhere may be its own outbox arriving from another client.
  const ours: Destination[] = ourDevices.map((device) => ({
    id: device.id,
    identityKey: device.identity_key,
    origin: "self" as const,
  }));

  const conversations = await listConversations();
  for (const conversation of conversations.conversations) {
    if (!conversationIds.has(conversation.id)) continue;
    try {
      const theirs = await readDirectory(conversation.other_user_id);
      candidates.set(conversation.id, [
        ...theirs.devices.map((device) => ({
          id: device.device_id,
          identityKey: device.identity_key,
          origin: "other" as const,
        })),
        ...ours,
      ]);
    } catch {
      // No longer reachable, or never was. This account's own devices are
      // still worth trying.
      candidates.set(conversation.id, ours);
    }
  }
  return candidates;
}

/**
 * Collect everything waiting for this device, decrypt it, and acknowledge.
 *
 * Acknowledging deletes the row on the server, so the local log is written
 * first — losing a message to a failed write is worse than collecting it twice.
 */
export async function collect(): Promise<string[]> {
  const { id: device, devices: ourDevices } = await ensureDeviceContext();
  const queue = await collectQueue({ device_id: device });
  if (queue.items.length === 0) return [];

  if (!(await accountPickle.get())) throw new Error("this device has no key store");

  // A pre-key message needs the sender's identity key, and the queue row
  // carries no sender. In a two-person conversation the sender is either the
  // other member or one of this account's own clients, so both are read once
  // per collection and tried in turn. Reading claims nothing, so it costs no
  // prekey.
  const candidates = await identitiesForPreKeys(
    new Set(
      queue.items.filter((item) => item.message_type === 0).map((item) => item.conversation_id)
    ),
    ourDevices
  );

  const touched = new Set<string>();
  const collected: number[] = [];

  for (const item of queue.items) {
    try {
      let plaintext: string;
      let mine: boolean;
      if (item.message_type === 0) {
        // Opening an inbound session spends a prekey out of the account, so it
        // goes through the same compare-and-swap as everything else that
        // advances it.
        const opened = await withAccount(async (pickle) => {
          for (const candidate of candidates.get(item.conversation_id) ?? []) {
            try {
              const session = await ratchet.createInboundSession(
                pickle,
                candidate.identityKey,
                item.payload
              );
              return {
                next: session.account_pickle,
                value: { session, origin: candidate.origin },
              };
            } catch {
              // Not this device. Try the next.
            }
          }
          return null;
        });
        if (opened === null) continue;
        await sessionPickle.set(opened.session.session_id, opened.session.session_pickle);
        // Which end a session belongs to is knowable now and never again: an
        // ordinary message arriving on it later names no sender.
        await sessionOrigin.set(opened.session.session_id, opened.origin);
        // The conversation's session list, not the device map keyed by a
        // conversation id: the other party may have several devices, and each
        // is its own ratchet.
        await sessionsInConversation.add(item.conversation_id, opened.session.session_id);
        plaintext = opened.session.plaintext;
        mine = opened.origin === "self";
      } else {
        // Which device sent this is not on the row, so the sessions this
        // conversation holds are tried in turn -- one per device, and the most
        // recently used first.
        const sessions = await sessionsInConversation.get(item.conversation_id);
        let read: { sessionId: string; plaintext: string } | null = null;
        for (const sessionId of sessions) {
          const pickle = await sessionPickle.get(sessionId);
          if (!pickle) continue;
          try {
            const decrypted = await ratchet.decrypt(pickle, item.message_type, item.payload);
            await sessionPickle.set(sessionId, decrypted.session_pickle);
            read = { sessionId, plaintext: decrypted.plaintext };
            break;
          } catch {
            // Not this session. Try the next.
          }
        }
        if (read === null) continue;
        plaintext = read.plaintext;
        mine = (await sessionOrigin.get(read.sessionId)) === "self";
      }
      await messageLog.append(item.conversation_id, {
        id: String(item.id),
        body: plaintext,
        at: item.created_at,
        // A message that arrived on one of this account's own sessions is the
        // sender's own outbox catching up, and belongs on the sender's side.
        mine,
      });
      touched.add(item.conversation_id);
      collected.push(item.id);
    } catch {
      // A message this device cannot read is left on the server rather than
      // acknowledged away: it stays collectable if the reason is fixable.
    }
  }

  if (collected.length > 0) {
    await ackQueue({ device_id: device, message_ids: collected });
  }
  return [...touched];
}

export type { StoredMessage };
export { messageLog };
