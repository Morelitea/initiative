/** Encrypting an envelope for everybody who should see it. */

import { sendMessagesApiV1MeDmConversationsConversationIdMessagesPost as sendMessages } from "@/api/generated/direct-messages/direct-messages";

import { ratchet } from "./client";
import { type Context, ensureDeviceContext } from "./device";
import { type Envelope, newMessageId } from "./envelope";
import {
  claimKeysFor,
  type Destination,
  establishedSession,
  openOutboundSession,
  withSession,
} from "./sessions";
import { messageLog, type ReceiptState, type StoredMessage, sessionsInConversation } from "./store";

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

/**
 * Every device the recipient has is being withheld pending a check.
 *
 * Separate from having no device at all, because the two need different
 * sentences and different next actions. "They have not set up encrypted
 * messages" is about the other person and there is nothing the reader can do;
 * this one is about a check the reader has not finished, on the notice beside
 * the composer, and it clears as soon as they do.
 */
export class RecipientDevicesUnverifiedError extends Error {
  constructor() {
    super("every device for that account is waiting on a safety-code check");
    this.name = "RecipientDevicesUnverifiedError";
  }
}

/**
 * Encrypt one envelope for each destination and hand the copies to the server.
 *
 * `to` is who it is for and `copies` who else keeps it -- this account's own
 * other devices. Nothing goes out unless it reached somebody in `to`: a copy
 * only this account's tabs hold would put a message in their thread that was
 * never said to anybody. `wake` is for the one envelope worth waking a phone
 * for: an install asking for the history it arrived without.
 */
export async function deliver(
  ctx: Context,
  conversationId: string,
  to: Destination[],
  copies: Destination[],
  envelope: Envelope,
  { silent, wake = false }: { silent: boolean; wake?: boolean }
): Promise<boolean> {
  const destinations = [...to, ...copies];
  const held = await Promise.all(
    destinations.map((destination) => establishedSession(destination.id))
  );
  // A session opened for one conversation carries this one too — a device of
  // this account's is in every conversation it has — so it is filed here as
  // well as where it was made.
  for (const session of held) {
    if (session) await sessionsInConversation.add(conversationId, session);
  }
  const missing = destinations.filter((_, index) => !held[index]);
  const claimed =
    missing.length > 0 ? await claimKeysFor(missing, ctx.device) : new Map<string, string>();

  const messages = [];
  let reached = false;
  for (const [index, destination] of destinations.entries()) {
    const oneTime = claimed.get(destination.id);
    // A device that published nothing we can open a session with is skipped:
    // that beats sending it something it cannot read.
    if (!held[index] && !oneTime) continue;
    const sessionId =
      held[index] ?? (await openOutboundSession(conversationId, destination, oneTime as string));
    const encrypted = await withSession(sessionId, async (pickle) => {
      const out = await ratchet.encrypt(pickle, JSON.stringify(envelope));
      return { next: out.session_pickle, value: out };
    });
    if (encrypted === null) continue;
    if (index < to.length) reached = true;
    messages.push({
      recipient_device_id: destination.id,
      message_type: encrypted.message_type,
      payload: encrypted.ciphertext,
    });
  }

  if (!reached) return false;
  await sendMessages(conversationId, { messages, silent, wake_own_devices: wake });
  return true;
}

/**
 * Encrypt one envelope for every device on the roster, one copy each: there is
 * no group key, so every member's copy travels on the pairwise ratchet that was
 * already there.
 *
 * Returns whether it reached anybody else at all. Anybody, not everybody: one
 * member with no devices published must not stop the rest hearing it.
 */
export async function sendEnvelope(
  ctx: Context,
  conversationId: string,
  memberIds: number[],
  envelope: Envelope,
  { toSelf, silent = false }: { toSelf: boolean; silent?: boolean }
): Promise<boolean> {
  // The directory rather than a claim: reading it spends nothing, and most
  // messages go to devices this one already has a session with.
  const directories = await Promise.all(
    memberIds.map(async (userId) => ({ userId, ...(await ctx.directory(userId)) }))
  );
  if (directories.every(({ devices }) => devices.length === 0)) {
    // Withholding is this client's own doing and is undone by acknowledging the
    // notice, so it is not the same outcome as an account with no device.
    if (directories.some(({ withheld }) => withheld > 0)) {
      throw new RecipientDevicesUnverifiedError();
    }
    return false;
  }

  const theirs: Destination[] = directories.flatMap(({ userId, devices }) =>
    devices.map((device) => ({
      id: device.device_id,
      identityKey: device.identity_key,
      origin: "other" as const,
      userId,
    }))
  );
  // A receipt is about their message and is for them, so it does not go to
  // this account's own tabs; an outgoing message does, or their copy of the
  // thread would be missing this side of it.
  const ours: Destination[] = toSelf
    ? ctx.ownDevices
        .filter((device) => device.id !== ctx.device)
        .map((device) => ({ id: device.id, identityKey: device.identity_key, origin: "self" }))
    : [];
  return deliver(ctx, conversationId, theirs, ours, envelope, { silent });
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
  memberIds: number[],
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
  // Refused before the log is written: nothing is sent, here or later, so the
  // thread should not show a message as though something had been.
  await sendToThread(conversationId, memberIds, envelope, false);
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
 * Send what a person did to the roster and this account's own other tabs, or
 * refuse when none of their devices could be opened.
 *
 * Acting on a message already said is `silent`: none of it is somebody saying
 * something, so none should arrive as a notification. Their client honours a
 * removal on its own copy, which is as far as anything here reaches: the
 * message was decrypted on their device and belongs to it.
 */
async function sendToThread(
  conversationId: string,
  memberIds: number[],
  envelope: Envelope,
  silent: boolean
): Promise<void> {
  const ctx = await ensureDeviceContext();
  if (!(await sendEnvelope(ctx, conversationId, memberIds, envelope, { toSelf: true, silent }))) {
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
  memberIds: number[],
  targetId: string,
  emoji: string,
  on: boolean
): Promise<boolean> {
  if (!(await actOn(conversationId, targetId, { own: false }))) return false;
  const envelope: Envelope = { v: 1, kind: "reaction", targetId, emoji, on };
  await sendToThread(conversationId, memberIds, envelope, true);
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
  memberIds: number[],
  targetId: string,
  body: string
): Promise<boolean> {
  const entry = await actOn(conversationId, targetId, { own: true });
  if (!entry || entry.body === body) return false;
  const at = new Date().toISOString();
  const rev = (entry.rev ?? 0) + 1;
  await sendToThread(
    conversationId,
    memberIds,
    { v: 1, kind: "edit", targetId, at, body, rev },
    true
  );
  return messageLog.applyEdit(conversationId, targetId, body, at, "mine", rev);
}

/** Take one of your own messages back. */
export async function sendRemove(
  conversationId: string,
  memberIds: number[],
  targetId: string
): Promise<boolean> {
  if (!(await actOn(conversationId, targetId, { own: true }))) return false;
  await sendToThread(conversationId, memberIds, { v: 1, kind: "remove", targetId }, true);
  return messageLog.applyRemove(conversationId, targetId, "mine", new Date().toISOString());
}

/**
 * Tell the other side how far their messages have got with this device.
 *
 * Best effort: a failure is swallowed. A receipt that does not arrive leaves
 * the thread exactly as it was, so there is nothing for the caller to do about
 * one. `ctx` is the collection's own; a look at a thread has none, and reads
 * a fresh one here.
 */
export async function acknowledge(
  ctx: Context | undefined,
  conversationId: string,
  memberIds: number[],
  ids: string[],
  state: ReceiptState
): Promise<void> {
  if (ids.length === 0) return;
  try {
    await sendEnvelope(
      ctx ?? (await ensureDeviceContext()),
      conversationId,
      memberIds,
      { v: 1, kind: "receipt", state, ids },
      // Nothing to announce: a receipt says a client collected or read
      // something, which is not a person saying anything to anybody.
      { toSelf: false, silent: true }
    );
  } catch {
    // Nothing to tell the reader: their thread is unchanged either way.
  }
}
