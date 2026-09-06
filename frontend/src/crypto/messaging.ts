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
  removeDeviceApiV1MeDmDevicesDeviceIdDelete as removeDevice,
  sendMessagesApiV1MeDmConversationsConversationIdMessagesPost as sendMessages,
  topUpKeysApiV1MeDmOneTimeKeysPost as topUpKeys,
} from "@/api/generated/direct-messages/direct-messages";
import type { DmDeviceRead } from "@/api/generated/initiativeAPI.schemas";

import { ratchet } from "./client";
import {
  accountPickle,
  allSessions,
  approvedDevices,
  deviceClaim,
  forgetDevice,
  type HistoryProgress,
  type HistoryRequest,
  historyAsk,
  historyProgress,
  lastRead,
  messageLog,
  pendingHistoryRequest,
  type ReceiptState,
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

/** How many times a key-store write is retried when another tab moves it first. */
const WRITE_ATTEMPTS = 3;

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
  for (let attempt = 0; attempt < WRITE_ATTEMPTS; attempt += 1) {
    const current = await accountPickle.get();
    if (!current) throw new Error("this device has no key store");
    const done = await work(current);
    if (done === null) return null;
    if (await accountPickle.swap(current, done.next)) return done.value;
  }
  return null;
}

/**
 * Advance one session, and only keep the result if nobody else moved it first.
 *
 * A ratchet step is a read and a write: encrypting moves the session on, and so
 * does decrypting. Two tabs that start from the same point both write, and the
 * one that lands second undoes the other — leaving a message the far end has no
 * state to open. `null` means this session could not carry the work, which is
 * the same answer a caller wants for a session that was simply the wrong one.
 */
async function withSession<T>(
  sessionId: string,
  work: (pickle: string) => Promise<{ next: string; value: T } | null>
): Promise<T | null> {
  for (let attempt = 0; attempt < WRITE_ATTEMPTS; attempt += 1) {
    const current = await sessionPickle.get(sessionId);
    if (!current) return null;
    const done = await work(current);
    if (done === null) return null;
    if (await sessionPickle.swap(sessionId, current, done.next)) return done.value;
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
  const turn = await deviceClaim.take();
  if (turn === null) {
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
    // The keys, the id and the claim in one write, and only while this is
    // still this tab's turn.
    if (!(await deviceClaim.settle(turn, created.id, keys.pickle))) {
      // Registration outran the claim and another tab took over. Its device is
      // the one this browser holds keys for, so the one just registered is
      // withdrawn rather than left collecting messages nothing can open.
      await removeDevice(created.id).catch(() => undefined);
      const id = await waitForRegistration(existing);
      return { id, devices: (await listDevices()).devices };
    }
    return { id: created.id, devices: response.devices };
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
  return (await ensureDeviceContext()).id;
}

/** Whether this browser has already been set up, without setting it up. */
export async function registeredDevice(): Promise<string | undefined> {
  return storedDeviceId.get();
}

/**
 * How much of one thread arrived after this device last looked at it.
 *
 * Counted by position in the log rather than by time: the log is append-only
 * and in the order this device learned of each message, which is the order the
 * thread is read in. A marker whose message is not in the log — a device whose
 * history was cleared under it — leaves everything unread, which is the side to
 * be wrong on.
 *
 * Only the other side counts: your own message is not news to you, and it lands
 * in the same log as theirs because the log is the whole thread.
 */
export async function unreadIn(conversationId: string): Promise<number> {
  const [log, seen] = await Promise.all([
    messageLog.get(conversationId),
    lastRead.get(conversationId),
  ]);
  const read = seen ? log.findIndex((message) => message.id === seen) : -1;
  return log.slice(read + 1).filter((message) => !message.mine).length;
}

/** This thread has been looked at, up to the last message the other side sent. */
export async function markRead(
  conversationId: string,
  { otherUserId, receipts = true }: { otherUserId?: number; receipts?: boolean } = {}
): Promise<void> {
  const [log, seen] = await Promise.all([
    messageLog.get(conversationId),
    lastRead.get(conversationId),
  ]);
  const previous = seen ? log.findIndex((message) => message.id === seen) : -1;
  // Only what this look actually read. Reporting the whole thread every time
  // the marker is touched would say "read" again on every keystroke that
  // lengthened it, for messages answered an hour ago.
  const newly = log.slice(previous + 1).filter((message) => !message.mine);
  if (newly.length === 0) return;

  await lastRead.set(conversationId, newly[newly.length - 1].id);
  if (receipts && otherUserId !== undefined) {
    await acknowledge(
      conversationId,
      otherUserId,
      newly.map((message) => message.id),
      "read"
    );
  }
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
  await allSessions.add(session.session_id);
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
 * What one message carries.
 *
 * The two sides need a name for a message that they both know, and neither of
 * the ids already to hand is one: the local id never leaves this device, and
 * the queue row's id belongs to one recipient device and is deleted when that
 * device collects. So the envelope carries an id of its own, which is what a
 * receipt names.
 *
 * The version is here because a message already sent cannot be rewritten, so
 * anything a later reader needs has to be in the first one.
 */
type Envelope =
  | { v: 1; kind: "text"; id: string; at: string; body: string; replyTo?: string }
  | { v: 1; kind: "receipt"; state: ReceiptState; ids: string[] }
  | { v: 1; kind: "reaction"; targetId: string; emoji: string; on: boolean }
  | { v: 1; kind: "edit"; targetId: string; at: string; body: string; rev: number }
  | { v: 1; kind: "remove"; targetId: string }
  // Between this account's own devices only. A device that has just been
  // registered holds no history and cannot derive any: it asks, and a device
  // that already has it answers if the person holding it agrees.
  | { v: 1; kind: "history-request"; requestId: string; deviceId: string; fingerprint: string }
  | {
      v: 1;
      kind: "history";
      requestId: string;
      seq: number;
      last: boolean;
      conversationId: string;
      messages: StoredMessage[];
    }
  | { v: 1; kind: "history-declined"; requestId: string };

/** A name for one message, known to both sides and to nobody else. */
const newMessageId = (): string =>
  typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** Every kind this version understands, so it can tell a later one from a broken one. */
const KNOWN_KINDS: ReadonlySet<string> = new Set<Envelope["kind"]>([
  "text",
  "receipt",
  "reaction",
  "edit",
  "remove",
  "history-request",
  "history",
  "history-declined",
]);

/** One entry of a thread, with the two fields everything else is hung off. */
const isStoredMessage = (value: unknown): value is StoredMessage => {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.id === "string" &&
    typeof entry.at === "string" &&
    typeof entry.body === "string" &&
    typeof entry.mine === "boolean"
  );
};

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((entry) => typeof entry === "string");

/**
 * Read what came out of the ratchet, whatever shape it is in.
 *
 * Every field a kind needs is checked before the envelope is believed. Half of
 * one is not a message with something missing -- it is an id this log would
 * file under `undefined`, where the next one like it looks like the same
 * message and is dropped as a duplicate. Anything that does not check out is
 * read as the plain body it may always have been, under the queue row's own id,
 * which is unique per item and cannot collide.
 */
function unpack(plaintext: string, fallbackId: string): Envelope | null {
  const asBody: Envelope = { v: 1, kind: "text", id: fallbackId, at: "", body: plaintext };
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(plaintext) as Record<string, unknown>;
  } catch {
    return asBody;
  }
  if (parsed?.v !== 1) return asBody;

  if (parsed.kind === "text" && typeof parsed.id === "string" && typeof parsed.body === "string") {
    return {
      v: 1,
      kind: "text",
      id: parsed.id,
      at: typeof parsed.at === "string" ? parsed.at : "",
      body: parsed.body,
      // A reply to a message this device never had is still a message: the
      // quote is dropped, the words are not.
      ...(typeof parsed.replyTo === "string" ? { replyTo: parsed.replyTo } : {}),
    };
  }
  if (
    parsed.kind === "reaction" &&
    typeof parsed.targetId === "string" &&
    typeof parsed.emoji === "string" &&
    typeof parsed.on === "boolean"
  ) {
    return {
      v: 1,
      kind: "reaction",
      targetId: parsed.targetId,
      emoji: parsed.emoji,
      on: parsed.on,
    };
  }
  if (
    parsed.kind === "edit" &&
    typeof parsed.targetId === "string" &&
    typeof parsed.body === "string"
  ) {
    return {
      v: 1,
      kind: "edit",
      targetId: parsed.targetId,
      at: typeof parsed.at === "string" ? parsed.at : "",
      body: parsed.body,
      // An edit from before revisions existed is the first one.
      rev: typeof parsed.rev === "number" ? parsed.rev : 1,
    };
  }
  if (parsed.kind === "remove" && typeof parsed.targetId === "string") {
    return { v: 1, kind: "remove", targetId: parsed.targetId };
  }
  if (
    parsed.kind === "receipt" &&
    (parsed.state === "delivered" || parsed.state === "read") &&
    isStringArray(parsed.ids)
  ) {
    return { v: 1, kind: "receipt", state: parsed.state, ids: parsed.ids };
  }
  if (
    parsed.kind === "history-request" &&
    typeof parsed.requestId === "string" &&
    typeof parsed.deviceId === "string" &&
    typeof parsed.fingerprint === "string"
  ) {
    return {
      v: 1,
      kind: "history-request",
      requestId: parsed.requestId,
      deviceId: parsed.deviceId,
      fingerprint: parsed.fingerprint,
    };
  }
  if (
    parsed.kind === "history" &&
    typeof parsed.requestId === "string" &&
    typeof parsed.seq === "number" &&
    typeof parsed.conversationId === "string" &&
    Array.isArray(parsed.messages)
  ) {
    return {
      v: 1,
      kind: "history",
      requestId: parsed.requestId,
      seq: parsed.seq,
      last: parsed.last === true,
      conversationId: parsed.conversationId,
      // Each entry is checked before it is believed, to the same standard as
      // every other kind here: one without the two fields a thread is read by
      // would be filed under `undefined`, where the next like it looks like the
      // same message.
      messages: parsed.messages.filter(isStoredMessage),
    };
  }
  if (parsed.kind === "history-declined" && typeof parsed.requestId === "string") {
    return { v: 1, kind: "history-declined", requestId: parsed.requestId };
  }
  // A kind this version does not know is from a later one, and is not for it to
  // guess at: printing the protocol into somebody's thread is the one outcome
  // worse than ignoring it. A kind it *does* know, arriving half-written, is a
  // different thing and still reads as the words it may always have been.
  if (typeof parsed.kind === "string" && !KNOWN_KINDS.has(parsed.kind)) return null;
  return asBody;
}

/**
 * Encrypt one envelope for every device that should see it and hand the
 * ciphertext to the server.
 *
 * Returns whether it reached the other party at all -- as opposed to only this
 * account's own devices, which is what "nobody there to read it" looks like
 * from here.
 */
async function sendEnvelope(
  conversationId: string,
  otherUserId: number,
  envelope: Envelope,
  { toSelf, silent = false }: { toSelf: boolean; silent?: boolean }
): Promise<boolean> {
  const { id: mine, devices: ourDevices } = await ensureDeviceContext();

  // The directory rather than a claim: reading it spends nothing, and most
  // messages go to devices this one already has a session with.
  const theirs = await readDirectory(otherUserId);
  if (theirs.devices.length === 0) return false;

  const destinations: Destination[] = [
    ...theirs.devices.map((device) => ({
      id: device.device_id,
      identityKey: device.identity_key,
      origin: "other" as const,
    })),
    // A receipt is about their message and is for them, so it does not go to
    // this account's own tabs; an outgoing message does, or their copy of the
    // thread would be missing this side of it.
    ...(toSelf
      ? ourDevices
          .filter((device) => device.id !== mine)
          .map((device) => ({
            id: device.id,
            identityKey: device.identity_key,
            origin: "self" as const,
          }))
      : []),
  ];

  const held = new Map<string, string | null>();
  for (const destination of destinations) {
    const session = await establishedSession(destination.id);
    held.set(destination.id, session);
    // A session opened for one conversation carries this one too — a device of
    // this account's is in every conversation it has — so it is filed here as
    // well as where it was made.
    if (session) await sessionsInConversation.add(conversationId, session);
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
    const encrypted = await withSession(sessionId, async (pickle) => {
      const out = await ratchet.encrypt(pickle, JSON.stringify(envelope));
      return { next: out.session_pickle, value: out };
    });
    if (encrypted === null) continue;
    if (destination.origin === "other") reachedThem = true;
    messages.push({
      recipient_device_id: destination.id,
      message_type: encrypted.message_type,
      payload: encrypted.ciphertext,
    });
  }

  // Nothing goes out at all if it could not reach them: an envelope this
  // account's own tabs hold and the other party never got would put a message
  // in their thread that was never said to anybody.
  if (!reachedThem) return false;

  await sendMessages(conversationId, { messages, silent });
  return true;
}

/**
 * Say one message for every device that should see it.
 *
 * The id and the time are minted once and encrypted for each of them, so every
 * copy of this message -- theirs, and this account's other tabs -- is the same
 * message rather than several that happen to read alike. That name is what a
 * receipt comes back naming.
 */
export async function sendText(
  conversationId: string,
  otherUserId: number,
  body: string,
  { replyTo }: { replyTo?: string } = {}
): Promise<StoredMessage> {
  const envelope: Envelope = {
    v: 1,
    kind: "text",
    id: newMessageId(),
    at: new Date().toISOString(),
    body,
    ...(replyTo ? { replyTo } : {}),
  };
  // Their devices were all there was to address and none could be opened.
  // Nothing is sent, here or later, so the thread should not show a message as
  // though something had been.
  if (!(await sendEnvelope(conversationId, otherUserId, envelope, { toSelf: true }))) {
    throw new RecipientHasNoDeviceError();
  }

  const stored: StoredMessage = {
    id: envelope.id,
    body,
    at: envelope.at,
    mine: true,
    ...(replyTo ? { replyTo } : {}),
  };
  await messageLog.append(conversationId, stored);
  return stored;
}

/**
 * Everything you can do to a message that has already been said.
 *
 * All three go to the other party *and* to this account's own other tabs, and
 * all three are silent: none of them is somebody saying something, so none
 * should arrive as a notification. They are applied to this device's own log
 * first, so the thread answers the click whether or not the send lands -- and
 * a send that fails leaves the two sides disagreeing about one emoji or one
 * edit, which is the same thing an offline device does anyway.
 *
 * Their client honours a removal on its own copy. That is as far as anything
 * here reaches: the message was decrypted on their device and belongs to it,
 * and no wording in this file can make that untrue.
 */
async function sendControl(
  conversationId: string,
  otherUserId: number,
  envelope: Envelope
): Promise<void> {
  if (
    !(await sendEnvelope(conversationId, otherUserId, envelope, { toSelf: true, silent: true }))
  ) {
    throw new RecipientHasNoDeviceError();
  }
}

/** The message a control envelope is about, if it is about anything. */
async function actOn(
  conversationId: string,
  targetId: string,
  { own }: { own: boolean }
): Promise<StoredMessage | null> {
  const entry = (await messageLog.get(conversationId)).find((m) => m.id === targetId);
  if (!entry || entry.removedAt) return null;
  return own && !entry.mine ? null : entry;
}

/**
 * Put one emoji on, or take it off, a message either side said.
 *
 * Sent before it is applied, and not applied at all if the send fails. The
 * other order reads better -- the thread answers the click at once -- and is
 * how the two sides come to disagree permanently: nothing here retries, so a
 * failure that had already been written down locally is one this device
 * believes and theirs never hears about.
 */
export async function sendReaction(
  conversationId: string,
  otherUserId: number,
  targetId: string,
  emoji: string,
  on: boolean
): Promise<boolean> {
  if (!(await actOn(conversationId, targetId, { own: false }))) return false;
  await sendControl(conversationId, otherUserId, { v: 1, kind: "reaction", targetId, emoji, on });
  return messageLog.applyReaction(conversationId, targetId, emoji, on, "mine");
}

/**
 * Rewrite one of your own messages.
 *
 * The revision, not the clock, is what orders two edits. Two devices of one
 * account can both be editing, and their clocks are set independently: a
 * correction made second can carry the earlier time and lose to the one it was
 * meant to replace, leaving the two devices holding different words forever.
 * A number that only goes up cannot do that, and where both devices reach the
 * same one the tie breaks the same way on each of them.
 */
export async function sendEdit(
  conversationId: string,
  otherUserId: number,
  targetId: string,
  body: string
): Promise<boolean> {
  const entry = await actOn(conversationId, targetId, { own: true });
  if (!entry || entry.body === body) return false;
  const at = new Date().toISOString();
  const rev = (entry.rev ?? 0) + 1;
  await sendControl(conversationId, otherUserId, { v: 1, kind: "edit", targetId, at, body, rev });
  return messageLog.applyEdit(conversationId, targetId, body, at, "mine", rev);
}

/** Take one of your own messages back. */
export async function sendRemove(
  conversationId: string,
  otherUserId: number,
  targetId: string
): Promise<boolean> {
  if (!(await actOn(conversationId, targetId, { own: true }))) return false;
  await sendControl(conversationId, otherUserId, { v: 1, kind: "remove", targetId });
  return messageLog.applyRemove(conversationId, targetId, "mine", new Date().toISOString());
}

/**
 * Tell the other side how far their messages have got with this device.
 *
 * Best effort: sent without waiting on anything, and a failure is swallowed.
 * A receipt that does not arrive leaves the thread exactly as it was, so there
 * is nothing for the caller to do about one.
 */
export async function acknowledge(
  conversationId: string,
  otherUserId: number,
  ids: string[],
  state: ReceiptState
): Promise<void> {
  if (ids.length === 0) return;
  try {
    await sendEnvelope(
      conversationId,
      otherUserId,
      { v: 1, kind: "receipt", state, ids },
      // Nothing to announce: a receipt says a client collected or read
      // something, which is not a person saying anything to anybody.
      { toSelf: false, silent: true }
    );
  } catch {
    // Nothing to tell the reader: their thread is unchanged either way.
  }
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
 * Read one queued message with a session this device already holds.
 *
 * Which device sent it is not on the row, so the conversation's own sessions
 * are tried first and then every other session this device holds: one opened
 * elsewhere can carry a message here, and a message that finds no session at
 * all is never readable again.
 */
async function readWithHeldSession(item: {
  conversation_id: string;
  message_type: number;
  payload: string;
}): Promise<{ sessionId: string; plaintext: string } | null> {
  const here = await sessionsInConversation.get(item.conversation_id);
  const sessions = [...here, ...(await allSessions.get()).filter((id) => !here.includes(id))];
  for (const sessionId of sessions) {
    const decrypted = await withSession(sessionId, async (pickle) => {
      try {
        const out = await ratchet.decrypt(pickle, item.message_type, item.payload);
        return { next: out.session_pickle, value: out };
      } catch {
        // Not this session. Try the next.
        return null;
      }
    });
    if (decrypted === null) continue;
    return { sessionId, plaintext: decrypted.plaintext };
  }
  return null;
}

/** How many messages of one conversation ride in a single envelope. */
const HISTORY_CHUNK = 40;

/**
 * Hand one envelope to one device of this account's own.
 *
 * Sync traffic is between two devices of the same person, so it needs no
 * recipient and gets no notification. It still has to ride inside a
 * conversation, because that is the only channel the server offers — but the
 * conversation it rides in is a carrier and nothing more: the envelope names
 * the conversation it is *about*, so history for one somebody can no longer be
 * written to still reaches the device that asked for it.
 */
async function sendToOwnDevice(
  carrierId: string,
  deviceId: string,
  identityKey: string,
  envelope: Envelope
): Promise<boolean> {
  const destination: Destination = { id: deviceId, identityKey, origin: "self" };
  let sessionId = await establishedSession(deviceId);
  if (!sessionId) {
    const claimed = await claimOwnSessionKeys({ device_id: await ensureDevice() });
    const key = claimed.devices.find((device) => device.device_id === deviceId)?.one_time_key;
    if (!key) return false;
    sessionId = await openOutboundSession(carrierId, destination, key.public_key);
  }
  const encrypted = await withSession(sessionId, async (pickle) => {
    const out = await ratchet.encrypt(pickle, JSON.stringify(envelope));
    return { next: out.session_pickle, value: out };
  });
  if (encrypted === null) return false;
  await sendMessages(carrierId, {
    messages: [
      {
        recipient_device_id: deviceId,
        message_type: encrypted.message_type,
        payload: encrypted.ciphertext,
      },
    ],
    // Nothing here is addressed to the other party, and nothing about it is
    // theirs to be told.
    silent: true,
  });
  return true;
}

/** A conversation any own-device traffic can travel inside. */
async function carrierConversation(): Promise<string | null> {
  const conversations = await listConversations();
  return conversations.conversations[0]?.id ?? null;
}

/**
 * Ask this account's other devices for the history this one cannot derive.
 *
 * Asked once per device: the answer is a person's decision, and a device that
 * asks again every time it starts is a device training somebody to say yes
 * without reading.
 */
export async function requestHistory(): Promise<boolean> {
  if ((await historyAsk.get()) !== undefined) return false;
  const { id: mine, devices } = await ensureDeviceContext();
  const me = devices.find((device) => device.id === mine);
  if (!me || devices.length < 2) return false;
  const carrier = await carrierConversation();
  if (carrier === null) return false;

  const requestId = newMessageId();
  let asked = false;
  for (const device of devices) {
    if (device.id === mine) continue;
    const sent = await sendToOwnDevice(carrier, device.id, device.identity_key, {
      v: 1,
      kind: "history-request",
      requestId,
      deviceId: mine,
      fingerprint: me.fingerprint_key,
    });
    asked = asked || sent;
  }
  // Written down once it is on its way rather than once it is answered: the
  // queue holds it until the far device wakes, and a device that asks on every
  // collection raises the same dialog until somebody stops reading it. The id
  // is what an answer is matched against.
  if (asked) await historyAsk.open(requestId);
  return asked;
}

/**
 * Write down a request to answer, unless this device has answered for that one
 * already.
 *
 * The fingerprint in the request is a convenience for the person comparing two
 * screens; what is checked is the directory's own entry for that device id. A
 * request that disagrees with it is not a device to ask about.
 */
async function noteHistoryRequest(
  envelope: Extract<Envelope, { kind: "history-request" }>,
  ourDevices: DmDeviceRead[]
): Promise<void> {
  const device = ourDevices.find((entry) => entry.id === envelope.deviceId);
  if (!device || device.fingerprint_key !== envelope.fingerprint) return;
  await pendingHistoryRequest.set({
    requestId: envelope.requestId,
    deviceId: device.id,
    label: device.label,
    fingerprint: device.fingerprint_key,
    at: new Date().toISOString(),
  });
}

/**
 * The request waiting on this device, if the person has not answered it.
 *
 * A device already approved is not asked about again — that is what approving a
 * device rather than a request means — so its request is not returned here and
 * is served instead.
 */
export async function historyRequestToAnswer(): Promise<HistoryRequest | undefined> {
  const pending = await pendingHistoryRequest.get();
  if (!pending) return undefined;
  if (await approvedDevices.holds(pending.deviceId, pending.fingerprint)) return undefined;
  return pending;
}

/** Say yes or no to the device waiting on an answer. */
export async function answerHistoryRequest(approve: boolean): Promise<void> {
  const pending = await pendingHistoryRequest.get();
  if (!pending) return;
  if (approve) {
    await approvedDevices.approve(pending.deviceId, pending.fingerprint);
    return;
  }
  await pendingHistoryRequest.clear();
  const carrier = await carrierConversation();
  const { devices } = await ensureDeviceContext();
  const device = devices.find((entry) => entry.id === pending.deviceId);
  if (carrier === null || !device) return;
  await sendToOwnDevice(carrier, device.id, device.identity_key, {
    v: 1,
    kind: "history-declined",
    requestId: pending.requestId,
  });
}

/**
 * Send this device's history to one that has been approved for it.
 *
 * Resumable from this side, which is the side that stops: a tab closed
 * mid-transfer picks up at the conversation it had reached, and what was
 * already sent is waiting in the queue for the far device whether or not this
 * one comes back.
 */
export async function serveHistory(): Promise<void> {
  const pending = await pendingHistoryRequest.get();
  if (!pending) return;
  if (!(await approvedDevices.holds(pending.deviceId, pending.fingerprint))) return;

  const { devices } = await ensureDeviceContext();
  const device = devices.find((entry) => entry.id === pending.deviceId);
  const carrier = await carrierConversation();
  if (!device || carrier === null || device.fingerprint_key !== pending.fingerprint) {
    // The device it was approved for is gone, or is not the one it was
    // approved as. Neither is a thing to keep trying.
    await pendingHistoryRequest.clear();
    return;
  }

  const held = await historyProgress.get(device.id);
  const progress: HistoryProgress =
    held?.requestId === pending.requestId
      ? held
      : { requestId: pending.requestId, done: [], seq: 0 };
  // What this device holds, not what the server still lists: a conversation
  // somebody left is off that list and its messages are still here.
  const conversations = await messageLog.conversations();

  for (const conversationId of conversations) {
    if (progress.done.includes(conversationId)) continue;
    const messages = await messageLog.get(conversationId);
    // Newest first: a transfer that runs out of room leaves the oldest behind
    // rather than a random half.
    const chunks: StoredMessage[][] = [];
    for (let index = messages.length; index > 0; index -= HISTORY_CHUNK) {
      chunks.push(messages.slice(Math.max(0, index - HISTORY_CHUNK), index));
    }
    if (chunks.length === 0) chunks.push([]);
    for (const chunk of chunks) {
      progress.seq += 1;
      const sent = await sendToOwnDevice(carrier, device.id, device.identity_key, {
        v: 1,
        kind: "history",
        requestId: pending.requestId,
        seq: progress.seq,
        last: false,
        conversationId,
        messages: chunk,
      });
      if (!sent) return;
      await historyProgress.set(device.id, progress);
    }
    progress.done.push(conversationId);
    await historyProgress.set(device.id, progress);
  }

  progress.seq += 1;
  await sendToOwnDevice(carrier, device.id, device.identity_key, {
    v: 1,
    kind: "history",
    requestId: pending.requestId,
    seq: progress.seq,
    last: true,
    conversationId: conversations[0] ?? "",
    messages: [],
  });
  await historyProgress.set(device.id, progress);
  await pendingHistoryRequest.clear();
}

/** Serve an approved request, without letting a failure stop a collection. */
async function serveApprovedHistory(): Promise<void> {
  try {
    await serveHistory();
  } catch {
    // Resumable from where it stopped; the next collection carries on.
  }
}

/**
 * Collect everything waiting for this device, decrypt it, and acknowledge.
 *
 * Acknowledging deletes the row on the server, so the local log is written
 * first — losing a message to a failed write is worse than collecting it twice.
 */
export async function collect({ receipts = true }: { receipts?: boolean } = {}): Promise<string[]> {
  const { id: device, devices: ourDevices } = await ensureDeviceContext();
  // Before the queue is read, and before the early return below it: a device
  // that has just arrived has nothing waiting, and asking is the whole reason
  // it has nothing.
  try {
    await requestHistory();
  } catch {
    // The next collection asks again.
  }
  const queue = await collectQueue({ device_id: device });
  if (queue.items.length === 0) {
    // An empty queue is not an idle device: a request approved a moment ago has
    // a transfer to run, and it was noted by an earlier collection rather than
    // this one.
    await serveApprovedHistory();
    return [];
  }

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
  /** Their messages that reached this device, per conversation, to report. */
  const landed = new Map<string, string[]>();

  for (const item of queue.items) {
    try {
      let plaintext: string;
      let mine: boolean;
      // Every message is offered to the sessions this device already holds
      // before any new one is opened -- pre-key messages included. A session
      // goes on marking what it sends as pre-key until it hears back on it, so
      // the second and third of those name a prekey the receiver has already
      // spent: opening a session is the one thing that cannot answer them, and
      // the session that can is sitting right here.
      const read = await readWithHeldSession(item);
      if (read !== null) {
        // Filed here, so the next message on it is found straight away.
        await sessionsInConversation.add(item.conversation_id, read.sessionId);
        plaintext = read.plaintext;
        mine = (await sessionOrigin.get(read.sessionId)) === "self";
      } else if (item.message_type === 0) {
        // Nothing held can read it, so it opens a conversation rather than
        // continuing one. Opening an inbound session spends a prekey out of the
        // account, so it goes through the same compare-and-swap as everything
        // else that advances it.
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
                value: { session, origin: candidate.origin, device: candidate.id },
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
        // Which device it is with, too -- and that is what the reply looks up.
        // Without it an answer opens a second session with somebody this device
        // is already talking to, spends another of their prekeys to do it, and
        // leaves the first session unestablished on both sides.
        await sessionForDevice.set(opened.device, opened.session.session_id);
        // The conversation's session list, not the device map keyed by a
        // conversation id: the other party may have several devices, and each
        // is its own ratchet.
        await sessionsInConversation.add(item.conversation_id, opened.session.session_id);
        await allSessions.add(opened.session.session_id);
        plaintext = opened.session.plaintext;
        mine = opened.origin === "self";
      } else {
        continue;
      }
      const envelope = unpack(plaintext, String(item.id));
      if (envelope === null) {
        // Understood well enough to know it is not for this version. Taken off
        // the server rather than left to be tried again on every collection.
        collected.push(item.id);
        continue;
      }

      // Acting on a message already said rather than saying one. Which side
      // an envelope arrived on is the whole of the authorization: one that
      // came over this account's own session is this account acting from
      // another tab, and one over theirs is them acting on their own message.
      if (envelope.kind === "reaction" || envelope.kind === "edit" || envelope.kind === "remove") {
        const from = mine ? "mine" : "theirs";
        const moved =
          envelope.kind === "reaction"
            ? await messageLog.applyReaction(
                item.conversation_id,
                envelope.targetId,
                envelope.emoji,
                envelope.on,
                from
              )
            : envelope.kind === "edit"
              ? await messageLog.applyEdit(
                  item.conversation_id,
                  envelope.targetId,
                  envelope.body,
                  envelope.at || item.created_at,
                  from,
                  envelope.rev
                )
              : await messageLog.applyRemove(
                  item.conversation_id,
                  envelope.targetId,
                  from,
                  item.created_at
                );
        if (moved) touched.add(item.conversation_id);
        collected.push(item.id);
        continue;
      }

      // Between this account's own devices, and only its own: these travel on
      // a session this device opened with another of its own, and are read
      // only there. An answer is also matched to the question this device
      // asked, so what arrives is what it went looking for.
      if (
        envelope.kind === "history-request" ||
        envelope.kind === "history" ||
        envelope.kind === "history-declined"
      ) {
        if (mine) {
          const ask = await historyAsk.get();
          const answers = typeof ask === "object" && ask.requestId === envelope.requestId;
          if (envelope.kind === "history-request") {
            await noteHistoryRequest(envelope, ourDevices);
          } else if (envelope.kind === "history" && answers) {
            if ((await messageLog.merge(envelope.conversationId, envelope.messages)) > 0) {
              touched.add(envelope.conversationId);
            }
            if (envelope.last) await historyAsk.close();
          } else if (envelope.kind === "history-declined" && answers) {
            // Answered, and the answer was no. Asking again is a person's
            // decision rather than something to retry into.
            await historyAsk.close();
          }
        }
        collected.push(item.id);
        continue;
      }

      if (envelope.kind === "receipt") {
        // Not a message: news about ones already sent. Their own tab reporting
        // is the sender's business, not this thread's, so a receipt that moved
        // nothing leaves the thread alone.
        if (await messageLog.markReceipts(item.conversation_id, envelope.ids, envelope.state)) {
          touched.add(item.conversation_id);
        }
        collected.push(item.id);
        continue;
      }

      await messageLog.append(item.conversation_id, {
        id: envelope.id,
        ...(envelope.replyTo ? { replyTo: envelope.replyTo } : {}),
        // The sender's own clock, so every copy of one message is dated alike
        // rather than by when each device happened to collect it.
        at: envelope.at || item.created_at,
        body: envelope.body,
        // A message that arrived on one of this account's own sessions is the
        // sender's own outbox catching up, and belongs on the sender's side.
        mine,
      });
      // Only theirs is worth reporting: this account already knows when it sent
      // its own, and a receipt addressed at yourself tells nobody anything.
      if (!mine) {
        const arrived = landed.get(item.conversation_id) ?? [];
        arrived.push(envelope.id);
        landed.set(item.conversation_id, arrived);
      }
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

  // After the acknowledgement, so a request that arrived in this batch is
  // served in it rather than a collection later.
  await serveApprovedHistory();

  // After the acknowledgement, and never in its way: a receipt is a courtesy
  // and the queue row it is about is already safely on this device.
  if (receipts && landed.size > 0) {
    const conversations = await listConversations();
    for (const conversation of conversations.conversations) {
      const ids = landed.get(conversation.id);
      if (ids) {
        await acknowledge(conversation.id, conversation.other_user_id, ids, "delivered");
      }
    }
  }
  return [...touched];
}

/**
 * Leave nothing behind on this browser, and stop messages being addressed to it.
 *
 * What signing out calls. A decrypted conversation must not outlive the session
 * that read it — a shared computer is the whole reason — and a device whose
 * keys are gone should not go on being sent to: withdrawing it releases
 * everything the server was holding for it.
 */
export async function forgetMessagesOnThisDevice(): Promise<void> {
  const existing = await storedDeviceId.get();
  if (existing) {
    // Best effort: the local store is cleared either way, and a device left
    // behind is withdrawn the next time this browser registers.
    await removeDevice(existing).catch(() => undefined);
  }
  await forgetDevice();
}

export type { StoredMessage };
export { messageLog };
