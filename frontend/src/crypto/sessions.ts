/** The account and sessions this device holds, and the only ways they move. */

import {
  claimOwnSessionKeysApiV1MeDmSessionKeysPost as claimOwnSessionKeys,
  claimSessionKeysApiV1UsersUserIdDmSessionKeysPost as claimSessionKeys,
} from "@/api/generated/direct-messages/direct-messages";

import { ratchet } from "./client";
import {
  accountPickle,
  allSessions,
  type SessionOrigin,
  sessionAuthor,
  sessionForDevice,
  sessionOrigin,
  sessionPickle,
  sessionsInConversation,
} from "./store";

/** How many times a key-store write is retried when another tab moves it first. */
const WRITE_ATTEMPTS = 3;

/** One destination for a message: a device, and whose it is. */
export interface Destination {
  id: string;
  identityKey: string;
  origin: SessionOrigin;
  /** Whose device this is. Absent on this account's own. */
  userId?: number;
}

/** One queued message read, and what its session says about who sent it. */
export interface Received {
  plaintext: string;
  mine: boolean;
  author?: number;
}

type Work<T> = (pickle: string) => Promise<{ next: string; value: T } | null>;

/**
 * Advance a pickle, and only keep the result if nobody else moved it first.
 *
 * Every ratchet step is a read and a write, from any number of tabs: the
 * account spends a prekey on each inbound session and mints fifty on a top-up,
 * and a session moves on with every message either way. Two tabs starting from
 * the same pickle both write, and the one that lands second undoes the other --
 * losing the private halves of published keys, or leaving a message the far end
 * has no state to open. So a writer that loses redoes its work against what is
 * stored.
 *
 * `work` returns `null` for "there is nothing I can do with this", and so does
 * this: a pickle that is not there, or a caller that never gets its turn, is
 * the same answer.
 */
async function advance<T>(
  get: () => Promise<string | undefined>,
  swap: (expected: string, next: string) => Promise<boolean>,
  work: Work<T>
): Promise<T | null> {
  for (let attempt = 0; attempt < WRITE_ATTEMPTS; attempt += 1) {
    const current = await get();
    if (!current) return null;
    const done = await work(current);
    if (done === null) return null;
    if (await swap(current, done.next)) return done.value;
  }
  return null;
}

export const withAccount = <T>(work: Work<T>) =>
  advance(accountPickle.get, accountPickle.swap, work);

export const withSession = <T>(sessionId: string, work: Work<T>) =>
  advance(
    () => sessionPickle.get(sessionId),
    (expected, next) => sessionPickle.swap(sessionId, expected, next),
    work
  );

/** The session already held with a device, if it is still usable. */
export async function establishedSession(deviceId: string): Promise<string | null> {
  const known = await sessionForDevice.get(deviceId);
  if (!known) return null;
  return (await sessionPickle.get(known)) ? known : null;
}

/**
 * Write down a session that has just been opened.
 *
 * Which end it belongs to and whose device it is are knowable now and never
 * again: an ordinary message arriving on it later names no sender. The device
 * is what a reply looks up, so an answer does not open a second session and
 * spend another of their prekeys; and it joins the conversation's list, since
 * the other party may have several devices, each its own ratchet.
 */
async function keepSession(
  conversationId: string,
  destination: Destination,
  sessionId: string,
  pickle: string
): Promise<void> {
  await sessionPickle.set(sessionId, pickle);
  await sessionOrigin.set(sessionId, destination.origin);
  if (destination.userId !== undefined) {
    await sessionAuthor.set(sessionId, destination.userId);
  }
  await sessionForDevice.set(destination.id, sessionId);
  await sessionsInConversation.add(conversationId, sessionId);
  await allSessions.add(sessionId);
}

export async function openOutboundSession(
  conversationId: string,
  destination: Destination,
  oneTimeKey: string
): Promise<string> {
  const account = await accountPickle.get();
  if (!account) throw new Error("this device has no key store");
  const session = await ratchet.createOutboundSession(account, destination.identityKey, oneTimeKey);
  await keepSession(conversationId, destination, session.session_id, session.session_pickle);
  return session.session_id;
}

/**
 * Open a session from a pre-key message that nothing held could read.
 *
 * It opens a conversation rather than continuing one. The queue row names no
 * sender, so each candidate device is tried in turn; the ratchet refuses an
 * identity that did not write the message. Opening an inbound session spends a
 * prekey out of the account, so it goes through the same compare-and-swap as
 * everything else that advances it.
 */
export async function openInboundSession(
  item: { conversation_id: string; payload: string },
  candidates: Destination[]
): Promise<Received | null> {
  const opened = await withAccount(async (pickle) => {
    for (const candidate of candidates) {
      try {
        const session = await ratchet.createInboundSession(
          pickle,
          candidate.identityKey,
          item.payload
        );
        return { next: session.account_pickle, value: { session, candidate } };
      } catch {
        // Not this device. Try the next.
      }
    }
    return null;
  });
  if (opened === null) return null;
  const { session, candidate } = opened;
  await keepSession(item.conversation_id, candidate, session.session_id, session.session_pickle);
  return {
    plaintext: session.plaintext,
    mine: candidate.origin === "self",
    author: candidate.userId,
  };
}

/**
 * Claim one prekey from each device that still needs a session opened with it.
 *
 * Claiming spends a key, so it is asked for only where there is nothing to
 * carry the message yet. An established conversation therefore costs neither
 * side a prekey, however many messages it carries.
 */
export async function claimKeysFor(
  missing: Destination[],
  ownDeviceId: string
): Promise<Map<string, string>> {
  const keys = new Map<string, string>();
  const claims = [];
  // One claim per account that still needs a session opened with it, rather
  // than one per device: the endpoint answers for the whole account, and asking
  // twice would spend two of their prekeys where one covers it.
  const accounts = new Set(
    missing
      .filter((destination) => destination.origin === "other")
      .map((destination) => destination.userId)
      .filter((userId): userId is number => userId !== undefined)
  );
  for (const userId of accounts) {
    claims.push(claimSessionKeys(userId));
  }
  if (missing.some((destination) => destination.origin === "self")) {
    claims.push(claimOwnSessionKeys({ device_id: ownDeviceId }));
  }
  // Settled rather than all: a claim can be refused after the directory was
  // read -- somebody's permission changes in between -- and one refusal must
  // not take the members whose keys did come back with it. A destination whose
  // key is missing is skipped further down, which is what a member with nothing
  // to open a session on already gets.
  for (const settled of await Promise.allSettled(claims)) {
    if (settled.status !== "fulfilled") continue;
    for (const device of settled.value.devices) {
      if (device.one_time_key) keys.set(device.device_id, device.one_time_key.public_key);
    }
  }
  return keys;
}

/**
 * Read one queued message with a session this device already holds.
 *
 * Which device sent it is not on the row, so the conversation's own sessions
 * are tried first and then every other session this device holds: one opened
 * elsewhere can carry a message here, and a message that finds no session at
 * all is never readable again.
 */
export async function readWithHeldSession(item: {
  conversation_id: string;
  message_type: number;
  payload: string;
}): Promise<Received | null> {
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
    // Filed here, so the next message on it is found straight away.
    await sessionsInConversation.add(item.conversation_id, sessionId);
    return {
      plaintext: decrypted.plaintext,
      mine: (await sessionOrigin.get(sessionId)) === "self",
      author: await sessionAuthor.get(sessionId),
    };
  }
  return null;
}
