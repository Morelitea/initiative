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
  claimSessionKeysApiV1UsersUserIdDmSessionKeysPost as claimSessionKeys,
  collectQueueApiV1MeDmQueueGet as collectQueue,
  listConversationsApiV1MeDmConversationsGet as listConversations,
  claimOwnSessionKeysApiV1MeDmSessionKeysPost as claimOwnSessionKeys,
  listDevicesApiV1MeDmDevicesGet as listDevices,
  readDirectoryApiV1UsersUserIdDmDevicesGet as readDirectory,
  registerDeviceApiV1MeDmDevicesPost as registerDevice,
  sendMessagesApiV1MeDmConversationsConversationIdMessagesPost as sendMessages,
} from "@/api/generated/direct-messages/direct-messages";

import { ratchet } from "./client";
import {
  accountPickle,
  messageLog,
  type StoredMessage,
  sessionForDevice,
  sessionPickle,
  sessionsInConversation,
  deviceId as storedDeviceId,
} from "./store";

/** How many prekeys a device keeps published. */
const KEY_POOL = 50;

/**
 * The id of this browser's device, registering it the first time.
 *
 * Registration publishes only public keys. The private halves stay inside the
 * account pickle, which never leaves this device.
 */
export async function ensureDevice(): Promise<string> {
  const existing = await storedDeviceId.get();
  if (existing) {
    // A device the server no longer knows about — revoked from another tab,
    // or the account erased — has to be re-registered rather than used.
    const devices = await listDevices();
    if (devices.devices.some((device) => device.id === existing)) return existing;
  }

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
  await accountPickle.set(keys.pickle);
  await storedDeviceId.set(created.id);
  return created.id;
}

async function outboundSessionFor(
  conversationId: string,
  deviceId: string,
  identityKey: string,
  oneTimeKey: string
): Promise<string> {
  const known = await sessionForDevice.get(deviceId);
  if (known) {
    const pickle = await sessionPickle.get(known);
    if (pickle) return known;
  }
  const account = await accountPickle.get();
  if (!account) throw new Error("this device has no key store");
  const session = await ratchet.createOutboundSession(account, identityKey, oneTimeKey);
  await sessionPickle.set(session.session_id, session.session_pickle);
  await sessionForDevice.set(deviceId, session.session_id);
  await sessionsInConversation.add(conversationId, session.session_id);
  return session.session_id;
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
  const mine = await ensureDevice();

  // Their devices and this account's others, claimed the same way: a device of
  // yours is a separate ratchet, so it needs its own session. Without this the
  // laptop's outbox never reaches the phone.
  const [theirs, ours] = await Promise.all([
    claimSessionKeys(otherUserId),
    claimOwnSessionKeys({ device_id: mine }),
  ]);
  const destinations = [...theirs.devices, ...ours.devices].map((device) => ({
    id: device.device_id,
    identity: device.identity_key,
    oneTime: device.one_time_key?.public_key ?? null,
  }));

  const messages = [];
  for (const destination of destinations) {
    if (!destination.oneTime) {
      // A device that published nothing we can open a session with. Skipping
      // beats sending it something it cannot read.
      continue;
    }
    const sessionId = await outboundSessionFor(
      conversationId,
      destination.id,
      destination.identity,
      destination.oneTime
    );
    const pickle = await sessionPickle.get(sessionId);
    if (!pickle) continue;
    const encrypted = await ratchet.encrypt(pickle, body);
    await sessionPickle.set(sessionId, encrypted.session_pickle);
    messages.push({
      recipient_device_id: destination.id,
      message_type: encrypted.message_type,
      payload: encrypted.ciphertext,
    });
  }

  if (messages.length > 0) {
    await sendMessages(conversationId, { messages });
  }

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
 * Collect everything waiting for this device, decrypt it, and acknowledge.
 *
 * Acknowledging deletes the row on the server, so the local log is written
 * first — losing a message to a failed write is worse than collecting it twice.
 */
export async function collect(): Promise<string[]> {
  const device = await ensureDevice();
  const queue = await collectQueue({ device_id: device });
  if (queue.items.length === 0) return [];

  const account = await accountPickle.get();
  if (!account) throw new Error("this device has no key store");

  // A pre-key message needs the sender's identity key, and the queue row
  // carries no sender. In a two-person conversation the sender is the other
  // member, so their published keys are read once per collection and tried in
  // turn -- a handful of devices, and it costs no prekey.
  const conversations = await listConversations();
  // Our own devices' keys are read once and tried everywhere: a pre-key message
  // in any conversation may be this account's own outbox arriving from another
  // client. Reading the directory claims nothing, so this costs no prekey.
  let ownKeys: string[] = [];
  try {
    ownKeys = (await listDevices()).devices.map((d) => d.identity_key);
  } catch {
    ownKeys = [];
  }
  const identityKeys = new Map<string, string[]>();
  for (const conversation of conversations.conversations) {
    try {
      const theirs = await readDirectory(conversation.other_user_id);
      identityKeys.set(conversation.id, [
        ...theirs.devices.map((device) => device.identity_key),
        ...ownKeys,
      ]);
    } catch {
      identityKeys.set(conversation.id, ownKeys);
    }
  }

  const touched = new Set<string>();
  const collected: number[] = [];
  let currentAccount = account;

  for (const item of queue.items) {
    try {
      let plaintext: string;
      if (item.message_type === 0) {
        const candidates = identityKeys.get(item.conversation_id) ?? [];
        let opened: Awaited<ReturnType<typeof ratchet.createInboundSession>> | null = null;
        for (const identity of candidates) {
          try {
            opened = await ratchet.createInboundSession(currentAccount, identity, item.payload);
            break;
          } catch {
            // Not this device of theirs. Try the next.
          }
        }
        if (opened === null) continue;
        currentAccount = opened.account_pickle;
        await accountPickle.set(currentAccount);
        await sessionPickle.set(opened.session_id, opened.session_pickle);
        // The conversation's session list, not the device map keyed by a
        // conversation id: the other party may have several devices, and each
        // is its own ratchet.
        await sessionsInConversation.add(item.conversation_id, opened.session_id);
        plaintext = opened.plaintext;
      } else {
        // Which of their devices sent this is not on the row, so the sessions
        // this conversation holds are tried in turn -- one per device of
        // theirs, and the most recently used first.
        const candidates = await sessionsInConversation.get(item.conversation_id);
        let read: { sessionId: string; plaintext: string } | null = null;
        for (const sessionId of candidates) {
          const pickle = await sessionPickle.get(sessionId);
          if (!pickle) continue;
          try {
            const decrypted = await ratchet.decrypt(pickle, item.message_type, item.payload);
            await sessionPickle.set(sessionId, decrypted.session_pickle);
            read = { sessionId, plaintext: decrypted.plaintext };
            break;
          } catch {
            // Not this session of theirs. Try the next.
          }
        }
        if (read === null) continue;
        plaintext = read.plaintext;
      }
      await messageLog.append(item.conversation_id, {
        id: String(item.id),
        body: plaintext,
        at: item.created_at,
        mine: false,
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
