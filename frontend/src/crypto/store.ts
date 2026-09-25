/**
 * Where a device's key store lives, and the one secret that protects it.
 *
 * vodozemac hands out pickles that are already encrypted under a 32-byte key,
 * so the only thing this module has to keep safe is that key. It is wrapped by
 * a **non-extractable** AES-GCM `CryptoKey`: the wrapping key's bytes never
 * exist in JavaScript, only the ability to call `decrypt` with it does.
 *
 * Both live in IndexedDB, which is per-origin on the web and app-private inside
 * the Capacitor WebView. Clearing site data destroys them, and that reads to
 * the user as "this device lost its history" — which is accurate, and has to be
 * said in the interface rather than discovered.
 *
 * This is deliberately not `@/lib/storage`: that module is a synchronous
 * key/value cache for small settings, and a ratchet store is binary, grows with
 * every session, and must never be mirrored anywhere it could be read back.
 */

import { toBase64 } from "@/lib/base64";

const DB_NAME = "initiative-dm";
const DB_VERSION = 1;
const STORE = "keys";
const WRAP_KEY = "wrap-key";
const PICKLE_KEY = "pickle-key";
const ACCOUNT = "account";
const DEVICE_ID = "device-id";
const SESSION_PREFIX = "session:";
const READ_PREFIX = "last-read:";

/** Where a wipe of this store is announced to every other realm. */
const DROPPED = "initiative-dm-dropped";

let connection: Promise<IDBDatabase> | null = null;

/**
 * The database, opened once per realm rather than on every read and write.
 * IndexedDB serialises overlapping `readwrite` transactions whichever
 * connection they are on. The connection is let go when another needs the
 * database to itself, or the browser closes it, and the next call reopens.
 */
function open(): Promise<IDBDatabase> {
  if (connection !== null) return connection;
  const opening = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE);
      }
    };
    request.onsuccess = () => {
      const db = request.result;
      const release = () => {
        if (connection === opening) connection = null;
      };
      db.onversionchange = () => {
        db.close();
        release();
      };
      db.onclose = release;
      resolve(db);
    };
    request.onerror = () => {
      if (connection === opening) connection = null;
      reject(request.error);
    };
  });
  connection = opening;
  return opening;
}

async function read<T>(key: string): Promise<T | undefined> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE, "readonly").objectStore(STORE).get(key);
    request.onsuccess = () => resolve(request.result as T | undefined);
    request.onerror = () => reject(request.error);
  });
}

async function write(key: string, value: unknown): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const request = db.transaction(STORE, "readwrite").objectStore(STORE).put(value, key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

/**
 * Read one key, transform it, and write it back — in a single transaction.
 *
 * IndexedDB serialises overlapping `readwrite` transactions across *every*
 * connection to the database, so this holds between tabs. A JavaScript lock
 * cannot: it lives in one tab's module scope, and the second tab never sees it.
 */
/**
 * Read-modify-write two keys inside ONE transaction.
 *
 * Two `update` calls are two transactions, and anything awaiting between them
 * observes the first without the second. Where those two writes are halves of
 * one fact -- this key changed, and it is held pending a check -- a reader that
 * sees only the first half draws the wrong conclusion from it.
 */
async function updatePair<A, B>(
  keyA: string,
  keyB: string,
  change: (a: A | undefined, b: B | undefined) => { a?: A; b?: B }
): Promise<void> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, "readwrite");
    const store = transaction.objectStore(STORE);
    const requestA = store.get(keyA);
    const requestB = store.get(keyB);
    let pending = 2;
    const both = () => {
      if (--pending > 0) return;
      const next = change(requestA.result as A | undefined, requestB.result as B | undefined);
      if (next.a !== undefined) store.put(next.a, keyA);
      if (next.b !== undefined) store.put(next.b, keyB);
    };
    requestA.onsuccess = both;
    requestB.onsuccess = both;
    requestA.onerror = () => reject(requestA.error);
    requestB.onerror = () => reject(requestB.error);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

async function update<T>(
  key: string,
  change: (current: T | undefined) => T | undefined
): Promise<{ written: boolean; value: T | undefined }> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, "readwrite");
    const store = transaction.objectStore(STORE);
    const request = store.get(key);
    let settled: { written: boolean; value: T | undefined } = {
      written: false,
      value: undefined,
    };
    request.onsuccess = () => {
      const current = request.result as T | undefined;
      const next = change(current);
      if (next === undefined) {
        settled = { written: false, value: current };
        return;
      }
      store.put(next, key);
      settled = { written: true, value: next };
    };
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => resolve(settled);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

async function drop(): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const request = db.transaction(STORE, "readwrite").objectStore(STORE).clear();
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel(DROPPED);
    channel.postMessage(null);
    channel.close();
  }
}

/**
 * Call `listener` whenever another realm wipes this store, for a realm that
 * keeps something it read from it. `false` where the browser has no way to say
 * so, which tells the caller not to keep anything.
 */
export function whenDropped(listener: () => void): boolean {
  if (typeof BroadcastChannel === "undefined") return false;
  new BroadcastChannel(DROPPED).onmessage = listener;
  return true;
}

async function wrappingKey(): Promise<CryptoKey> {
  const existing = await read<CryptoKey>(WRAP_KEY);
  if (existing) return existing;
  // Not extractable: the bytes never reach JavaScript. What is stored is the
  // handle, and using it means asking the browser to decrypt with it.
  const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, [
    "encrypt",
    "decrypt",
  ]);
  await write(WRAP_KEY, key);
  return key;
}

/**
 * The pickle key for this device, minted on first use.
 *
 * Stored only as ciphertext under the non-extractable wrapping key above.
 */
export async function pickleKey(): Promise<string> {
  const key = await wrappingKey();
  // Both halves are stored as plain ArrayBuffers: structured clone keeps them
  // exactly, and reading them back as a fresh view avoids the SharedArrayBuffer
  // widening that `Uint8Array` alone carries in the DOM types.
  const stored = await read<{ iv: ArrayBuffer; data: ArrayBuffer }>(PICKLE_KEY);
  if (stored) {
    const raw = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: new Uint8Array(stored.iv) },
      key,
      stored.data
    );
    return toBase64(new Uint8Array(raw));
  }
  const raw = crypto.getRandomValues(new Uint8Array(32));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, raw);
  await write(PICKLE_KEY, { iv: iv.buffer, data });
  return toBase64(raw);
}

/**
 * Who is allowed to register this browser's device.
 *
 * Registration is a network round trip, so it cannot sit inside one database
 * transaction. Two tabs opening Messages for the first time would otherwise
 * both create an account and both register: the server would hold two devices,
 * only one set of private keys would survive the last write, and anything sent
 * to the other would never be readable.
 *
 * So the *right* to register is claimed atomically first, and the loser waits
 * for the winner's answer. A claim that was abandoned — the tab closed
 * mid-registration — goes stale and can be taken again.
 */
export type DeviceClaim =
  | { status: "claiming"; at: number; token: string }
  | { status: "ready"; deviceId: string };

const DEVICE_CLAIM = "device-claim";
const CLAIM_STALE_MS = 30_000;

export const deviceClaim = {
  read: () => read<DeviceClaim>(DEVICE_CLAIM),

  /**
   * A token if this caller may register, `null` if somebody else is on it.
   *
   * The token is what makes a turn *this* caller's. A registration that runs
   * past the stale window is taken over by the next tab, and the slow one has
   * to be able to find out that what it is holding is no longer the turn.
   */
  take: async (): Promise<string | null> => {
    const now = Date.now();
    const token = crypto.randomUUID();
    const { written } = await update<DeviceClaim>(DEVICE_CLAIM, (current) => {
      if (current?.status === "ready") return undefined;
      if (current?.status === "claiming" && now - current.at < CLAIM_STALE_MS) {
        return undefined;
      }
      return { status: "claiming", at: now, token };
    });
    return written ? token : null;
  },

  /**
   * Record a finished registration: the keys, the id and the claim at once.
   *
   * All three in one transaction, and only for the caller whose turn it still
   * is. What a device id refers to is then always present beside it, and a tab
   * that was taken over cannot write its own account over the one this browser
   * actually registered. `false` means the turn was lost.
   */
  settle: async (token: string, deviceId: string, pickle: string): Promise<boolean> => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE, "readwrite");
      const store = transaction.objectStore(STORE);
      const request = store.get(DEVICE_CLAIM);
      let settled = false;
      request.onsuccess = () => {
        const current = request.result as DeviceClaim | undefined;
        if (current?.status !== "claiming" || current.token !== token) return;
        store.put(pickle, ACCOUNT);
        store.put(deviceId, DEVICE_ID);
        store.put({ status: "ready", deviceId }, DEVICE_CLAIM);
        settled = true;
      };
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => resolve(settled);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  },

  /**
   * Give up on a device the server no longer knows, so it can be replaced.
   *
   * Only a settled claim naming that exact device is reopened. One already
   * being registered under is left alone: two tabs noticing the same revocation
   * still produce one device between them, rather than one each.
   */
  invalidate: async (deviceId: string): Promise<void> => {
    await update<DeviceClaim>(DEVICE_CLAIM, (current) =>
      current?.status === "ready" && current.deviceId === deviceId
        ? { status: "claiming", at: 0, token: "" }
        : undefined
    );
  },

  /** Let go of a turn this caller could not finish, if it is still theirs. */
  release: async (token: string): Promise<void> => {
    await update<DeviceClaim>(DEVICE_CLAIM, (current) =>
      current?.status === "claiming" && current.token === token
        ? { status: "claiming", at: 0, token: "" }
        : undefined
    );
  },
};

export const accountPickle = {
  get: () => read<string>(ACCOUNT),
  set: (pickle: string) => write(ACCOUNT, pickle),
  /**
   * Replace the account only if it is still the one that was read.
   *
   * The account holds the private half of every prekey it has published, and
   * more than one thing advances it: collecting a pre-key message spends a key,
   * topping the pool up mints fifty. Two tabs doing that from the same starting
   * pickle each write a different account, and the loser's keys are already
   * published — a sender that claims one opens a session this device cannot.
   * So a writer that finds the account moved under it is told, and redoes its
   * work against what is actually stored.
   */
  swap: async (expected: string, next: string): Promise<boolean> => {
    const { written } = await update<string>(ACCOUNT, (current) =>
      current === expected ? next : undefined
    );
    return written;
  },
};

export const deviceId = {
  get: () => read<string>(DEVICE_ID),
  set: (id: string) => write(DEVICE_ID, id),
};

/**
 * The account this browser's device belongs to. A device signs its keys as
 * this account's, and the account's own devices are checked against it.
 */
export const deviceOwner = {
  get: () => read<number>("device-owner"),
  set: (userId: number) => write("device-owner", userId),
};

/**
 * When this browser first checked device signatures, in epoch milliseconds.
 *
 * A device registered before signing existed carries none until its owner next
 * opens the app. The grace for those is counted from here, so it is the same
 * window for every device this browser meets.
 */
export const signingSince = {
  mark: async (): Promise<number> =>
    (
      await update<number>("signing-since", (current) =>
        current === undefined ? Date.now() : undefined
      )
    ).value as number,
};

/**
 * The last message this device has looked at, per conversation, by its id.
 *
 * Kept here rather than on the server for the same reason the log is: nobody
 * else can see inside a thread, so nobody else can say what has been read. It
 * is per device by consequence — reading a thread on a phone leaves it unread
 * on a laptop, which matches a history that is also per device.
 *
 * An id rather than a time. The two sides stamp their messages from two clocks
 * — theirs by the server, mine by this browser — and two messages can land in
 * the same millisecond, so neither the instant nor the ordering of instants is
 * something to count against. A place in the log is exact.
 */
export const lastRead = {
  get: (conversationId: string) => read<string>(READ_PREFIX + conversationId),
  set: (conversationId: string, messageId: string) =>
    write(READ_PREFIX + conversationId, messageId),
};

/**
 * What this device has read, per conversation.
 *
 * The client is the archive: the server deletes a message the moment it is
 * collected, so if this is not written down the message is gone. Kept beside
 * the ratchet rather than in React state for the same reason.
 */
/**
 * How far one of your own messages has got.
 *
 * Only ever set on a message you sent: the other side reports it, so there is
 * nothing to report about theirs. Absent means nothing has come back yet, which
 * is also what it looks like when they have receipts switched off.
 */
export type ReceiptState = "delivered" | "read";

/** Later states never fall back to earlier ones, whatever order they arrive in. */
const reached = (state: ReceiptState | undefined): number =>
  state === "read" ? 2 : state === "delivered" ? 1 : 0;

/**
 * Who has picked one emoji on one message.
 *
 * A direct message has exactly two people in it, so which sides picked it is
 * the whole truth -- there is no list of reactors to keep, and no count to
 * derive that `mine + theirs` does not already give.
 */
export interface ReactionSides {
  mine: boolean;
  theirs: boolean;
}

export interface StoredMessage {
  id: string;
  body: string;
  at: string;
  mine: boolean;
  /**
   * Which account said it. Absent on this account's own, and on anything
   * stored before a thread could hold more than two people.
   */
  author?: number;
  receipt?: ReceiptState;
  /** The message this one answers, by the name both sides know it under. */
  replyTo?: string;
  /** When its author last changed the body. Absent means never. */
  editedAt?: string;
  /**
   * How many times its author has changed it, counting only upwards.
   *
   * What orders two edits, in place of the clock: an account's devices set
   * theirs independently, so a correction made second can carry the earlier
   * time and lose to the one it was meant to replace.
   */
  rev?: number;
  /** Emoji, and who is behind each. An emoji nobody holds is dropped. */
  reactions?: Record<string, ReactionSides>;
  /**
   * When its author took it back. The entry stays, without its words.
   *
   * A gap where a message was is a worse answer than a line saying one was
   * removed: a thread that closes over it leaves the other person re-reading
   * an exchange that no longer makes sense.
   */
  removedAt?: string;
}

/**
 * Which side of the conversation an instruction came from.
 *
 * Editing and removing are only ever a person acting on their own message, so
 * this is the whole of the authorization: an envelope from them may change
 * what they said, and nothing else. It is checked here rather than at the call
 * site, because the call site is a client and the log is the only copy.
 */
export type Side = "mine" | "theirs";

const LOG_PREFIX = "log:";

/**
 * Whether an envelope from ``author`` may act on ``entry``.
 *
 * The side it arrived on, and then who sent it. The side alone was the whole of
 * it while "theirs" meant one person; on a roster it means several, and an edit
 * or a removal is a claim about a message's author rather than about its side.
 *
 * Authors are compared only where both are known. A thread whose messages
 * predate this, or a session opened before it, has no author to compare — and
 * every one of those is a pair, where the side already answers the question.
 */
const mayActOn = (entry: StoredMessage, from: Side, author?: number): boolean => {
  if (entry.mine !== (from === "mine")) return false;
  if (entry.author === undefined || author === undefined) return true;
  return entry.author === author;
};

export const messageLog = {
  get: async (conversationId: string): Promise<StoredMessage[]> =>
    (await read<StoredMessage[]>(LOG_PREFIX + conversationId)) ?? [],
  /**
   * Add one message, keeping whatever else arrived at the same moment.
   *
   * Sending and collecting both append, from any number of open tabs, and all
   * of them share one database. A plain read-then-write loses whichever
   * finishes first — on the only copy of that message this device has.
   */
  append: async (conversationId: string, message: StoredMessage): Promise<void> => {
    await update<StoredMessage[]>(LOG_PREFIX + conversationId, (existing) => {
      const current = existing ?? [];
      if (current.some((entry) => entry.id === message.id)) return undefined;
      return [...current, message];
    });
  },
  /**
   * Add the messages of this conversation that this device does not have.
   *
   * Only the ones it is missing. An entry already here is left exactly as it
   * is: this device has held that message since it arrived, so it has also had
   * every edit, reaction and receipt that followed — a second copy of it from
   * somewhere else has nothing to add and no way to be newer.
   *
   * One transaction for the whole batch, because a live message and a second
   * tab can both land while a transfer is running.
   *
   * Returns how many entries were new, which is the only part worth reporting.
   */
  merge: async (conversationId: string, incoming: StoredMessage[]): Promise<number> => {
    let added = 0;
    await update<StoredMessage[]>(LOG_PREFIX + conversationId, (existing) => {
      const current = existing ?? [];
      const held = new Set(current.map((entry) => entry.id));
      const missing = incoming.filter((message) => !held.has(message.id));
      added = missing.length;
      if (added === 0) return undefined;
      // By the sender's clock: what orders a thread is when each message was
      // written, not the order two devices happened to exchange them in.
      return [...current, ...missing].sort((left, right) => left.at.localeCompare(right.at));
    });
    return added;
  },
  /**
   * Every conversation this device has a thread for.
   *
   * Read from the store rather than from the server's list: a conversation
   * somebody left is gone from that list and its messages are still here, and
   * they are as much this device's history as any other.
   */
  /**
   * Whether this device holds any thread at all.
   *
   * A conversation key can outlive the last message in it — every message in a
   * thread can be taken back — so the messages are what is counted rather than
   * the keys.
   */
  holdsAnything: async (): Promise<boolean> => {
    for (const conversationId of await messageLog.conversations()) {
      if ((await messageLog.get(conversationId)).length > 0) return true;
    }
    return false;
  },
  conversations: async (): Promise<string[]> => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const request = db.transaction(STORE, "readonly").objectStore(STORE).getAllKeys();
      request.onsuccess = () =>
        resolve(
          (request.result as IDBValidKey[])
            .filter((key): key is string => typeof key === "string")
            .filter((key) => key.startsWith(LOG_PREFIX))
            .map((key) => key.slice(LOG_PREFIX.length))
        );
      request.onerror = () => reject(request.error);
    });
  },
  /**
   * Record how far some of your own messages have got.
   *
   * Receipts arrive out of order -- a device that was away collects a read and
   * a delivered in one go -- so a state only ever moves forward. Ids this log
   * does not hold are ignored: a receipt for a message this device never had is
   * about one of your other devices' copies.
   */
  markReceipts: async (
    conversationId: string,
    ids: string[],
    state: ReceiptState
  ): Promise<boolean> => {
    if (ids.length === 0) return false;
    const wanted = new Set(ids);
    let changed = false;
    await update<StoredMessage[]>(LOG_PREFIX + conversationId, (existing) => {
      const current = existing ?? [];
      const next = current.map((entry) => {
        if (!entry.mine || !wanted.has(entry.id)) return entry;
        if (reached(state) <= reached(entry.receipt)) return entry;
        changed = true;
        return { ...entry, receipt: state };
      });
      return changed ? next : undefined;
    });
    return changed;
  },
  /**
   * Turn one emoji on or off for one message, from one side.
   *
   * Idempotent, because both sides' copies of an envelope can arrive twice --
   * a tab that collected it and a tab that sent it -- and a reaction is a
   * state rather than a tally.
   */
  applyReaction: async (
    conversationId: string,
    targetId: string,
    emoji: string,
    on: boolean,
    from: Side
  ): Promise<boolean> => {
    let changed = false;
    await update<StoredMessage[]>(LOG_PREFIX + conversationId, (existing) => {
      const current = existing ?? [];
      const next = current.map((entry) => {
        // Nothing lands on a message that has been taken back: there is no
        // longer anything there to be about.
        if (entry.id !== targetId || entry.removedAt) return entry;
        const held = entry.reactions?.[emoji] ?? { mine: false, theirs: false };
        if (held[from] === on) return entry;
        changed = true;
        const sides = { ...held, [from]: on };
        const reactions = { ...entry.reactions };
        // Nobody holds it any more, so it stops being a reaction rather than
        // becoming one with no one behind it.
        if (!sides.mine && !sides.theirs) delete reactions[emoji];
        else reactions[emoji] = sides;
        return { ...entry, reactions };
      });
      return changed ? next : undefined;
    });
    return changed;
  },
  /**
   * Rewrite what one message says.
   *
   * Only the side that said it: an envelope from them can change their own
   * message and nothing else, whatever it claims to target.
   */
  applyEdit: async (
    conversationId: string,
    targetId: string,
    body: string,
    at: string,
    from: Side,
    rev: number,
    author?: number
  ): Promise<boolean> => {
    let changed = false;
    await update<StoredMessage[]>(LOG_PREFIX + conversationId, (existing) => {
      const current = existing ?? [];
      const next = current.map((entry) => {
        if (entry.id !== targetId || !mayActOn(entry, from, author)) return entry;
        if (entry.removedAt || entry.body === body) return entry;
        const held = entry.rev ?? 0;
        // An edit that arrives after a later one is an old edit, whichever
        // order the two of them were collected in. Two devices reaching the
        // same revision at once break the tie on the words themselves, so
        // every device that sees both lands on the same one -- an arbitrary
        // answer that agrees beats a sensible one that does not.
        if (rev < held) return entry;
        if (rev === held && !(body > entry.body)) return entry;
        changed = true;
        return { ...entry, body, editedAt: at, rev };
      });
      return changed ? next : undefined;
    });
    return changed;
  },
  /**
   * Take back what one message said, leaving the fact that it was said.
   *
   * The words go and the entry stays: a thread that closed over the gap would
   * leave the other person re-reading an exchange with a hole in it, and any
   * reply that answered it pointing at nothing.
   *
   * Same rule as an edit -- only its author's side may -- and the same limit as
   * everything else here: this is the copy this device holds. Their client
   * honours the same envelope on theirs, which is as far as any of this can
   * reach.
   */
  applyRemove: async (
    conversationId: string,
    targetId: string,
    from: Side,
    at: string,
    author?: number
  ): Promise<boolean> => {
    let changed = false;
    await update<StoredMessage[]>(LOG_PREFIX + conversationId, (existing) => {
      const current = existing ?? [];
      const next = current.map((entry) => {
        if (entry.id !== targetId || !mayActOn(entry, from, author)) return entry;
        if (entry.removedAt) return entry;
        changed = true;
        // Rebuilt rather than spread: the body, the reactions and the receipt
        // all go with it, and a spread would carry whichever of them this
        // version happens not to name.
        return {
          id: entry.id,
          at: entry.at,
          mine: entry.mine,
          author: entry.author,
          replyTo: entry.replyTo,
          body: "",
          removedAt: at,
        };
      });
      return changed ? next : undefined;
    });
    return changed;
  },
};

/**
 * The devices this one has agreed to send its history to, when the person
 * confirmed them.
 *
 * Kept against the fingerprint each had when it was approved, so an entry in
 * the directory whose key has changed since is a different device wearing a
 * familiar name. A device id belongs to one registration — signing out
 * withdraws it — so an approval cannot outlive the device that earned it.
 */
/**
 * What the person said about sending each of their own devices this device's
 * history, keyed by device and bound to its fingerprint. A plain fingerprint is
 * a yes recorded before a no could be.
 */
type HistoryDecision = string | { fingerprint: string; send: boolean };

const historyDecision = async (deviceId: string, fingerprint: string) => {
  const decision = (await read<Record<string, HistoryDecision>>("history-approved"))?.[deviceId];
  if (typeof decision === "string") return decision === fingerprint ? true : undefined;
  return decision?.fingerprint === fingerprint ? decision.send : undefined;
};

export const approvedDevices = {
  /** Yes, no, or `undefined` where the person has not been asked. */
  decision: historyDecision,
  decide: async (deviceId: string, fingerprint: string, send: boolean): Promise<void> => {
    await update<Record<string, HistoryDecision>>("history-approved", (existing) => ({
      ...(existing ?? {}),
      [deviceId]: { fingerprint, send },
    }));
  },
};

/** A device's two public keys: the one it signs with and the one sessions start from. */
export interface DeviceKeys {
  fingerprint: string;
  identityKey: string;
}

/**
 * The device keys this browser has seen for each conversation partner, and for
 * this account's own devices.
 *
 * The directory is served by the platform, so a key it returns is remembered
 * here rather than trusted afresh on every read.
 *
 * The first directory read says nothing: that is trust-on-first-use, and a
 * warning there would fire on every new conversation. Once this browser has a
 * baseline for the partner, both a replaced key and a newly introduced device
 * are changes worth interrupting for. Registering a replacement receives a new
 * server UUID, so matching on device id alone would treat either as a first
 * sighting.
 *
 * Per partner, keyed by their device id.
 */
export interface PeerKeyChange {
  userId: number;
  deviceId: string;
  /** What this browser held for the device before. Absent for a new device. */
  was?: DeviceKeys;
  /** What the directory returned now. */
  now: DeviceKeys;
  at: string;
  /** The device's own name for itself, for one of this account's own. */
  label?: string | null;
  /** One of this account's own that has something waiting for this device. */
  asked?: true;
}

const PEER_KEYS_PREFIX = "peer-keys:";
const PEER_CHANGES = "peer-key-changes";
const VERIFIED_PAIRS = "verified-pairs";

interface RememberedPeerKey {
  fingerprint: string;
  /** Absent only for records written before identities were bound here. */
  identityKey?: string;
}

type StoredPeerKey = string | RememberedPeerKey;

const rememberedPeerKey = (stored: StoredPeerKey): RememberedPeerKey =>
  typeof stored === "string" ? { fingerprint: stored } : stored;

export const peerDeviceKeys = {
  all: async (userId: number): Promise<Record<string, StoredPeerKey>> =>
    (await read<Record<string, StoredPeerKey>>(PEER_KEYS_PREFIX + userId)) ?? {},
  /**
   * Record what the directory returned, report the keys that changed, and hold
   * them pending a check -- all in one transaction.
   *
   * Remembering, comparing and holding are one step on purpose. Any split lets
   * them interleave, and both splits are reachable through an ordinary `await`
   * with two sends in flight:
   *
   * - remember and compare apart: the first send writes the new key before the
   *   second compares, and the second sees no change;
   * - compare and hold apart: the first send has written the new key but not
   *   yet the hold, and the second finds nothing changed AND nothing held, so
   *   the device reads as addressable and the message goes to a key nobody has
   *   checked.
   *
   * The second is the one that matters, because the whole point of the hold is
   * that a send finds it.
   */
  reconcile: async (
    userId: number,
    seen: {
      deviceId: string;
      fingerprint: string;
      identityKey: string;
      label?: string | null;
      previouslyAddressed?: boolean;
    }[]
  ): Promise<PeerKeyChange[]> => {
    const changes: PeerKeyChange[] = [];
    const at = new Date().toISOString();
    await updatePair<Record<string, StoredPeerKey>, PeerKeyChange[]>(
      PEER_KEYS_PREFIX + userId,
      PEER_CHANGES,
      (existing, heldNow) => {
        const known = existing ?? {};
        const hasBaseline = Object.keys(known).length > 0;
        const next = { ...known };
        for (const { deviceId, fingerprint, identityKey, label, previouslyAddressed } of seen) {
          const stored = known[deviceId];
          const knownKey = stored === undefined ? undefined : rememberedPeerKey(stored);
          const keyChanged =
            knownKey !== undefined &&
            (knownKey.fingerprint !== fingerprint || knownKey.identityKey !== identityKey);
          if (keyChanged || (stored === undefined && (hasBaseline || previouslyAddressed))) {
            changes.push({
              userId,
              deviceId,
              ...(knownKey?.identityKey
                ? { was: { fingerprint: knownKey.fingerprint, identityKey: knownKey.identityKey } }
                : {}),
              now: { fingerprint, identityKey },
              at,
              ...(label !== undefined ? { label } : {}),
            });
          }
          next[deviceId] = { fingerprint, identityKey };
        }
        // Devices that stopped being listed are left in place, so a device that
        // disappears and comes back with a different key is still a change
        // rather than a first sighting.
        if (changes.length === 0) return { a: next };
        // One entry per device, the latest finding standing for it.
        const byDevice = new Map((heldNow ?? []).map((change) => [change.deviceId, change]));
        for (const change of changes) byDevice.set(change.deviceId, change);
        return { a: next, b: [...byDevice.values()] };
      }
    );
    return changes;
  },
  forget: async (userId: number): Promise<void> => {
    await write(PEER_KEYS_PREFIX + userId, undefined);
  },
};

/**
 * Changes waiting to be shown to the person using this browser.
 *
 * Held rather than raised inline: the send path cannot put something on
 * screen, and a change found while sending has to survive until it has been.
 */
export const peerKeyChanges = {
  all: async (): Promise<PeerKeyChange[]> => (await read<PeerKeyChange[]>(PEER_CHANGES)) ?? [],
  /** Put a device in front of the person, whether or not its keys changed. */
  raise: async (change: PeerKeyChange): Promise<void> => {
    await update<PeerKeyChange[]>(PEER_CHANGES, (existing) => [
      ...(existing ?? []).filter((held) => held.deviceId !== change.deviceId),
      change,
    ]);
  },
  /** Note the held devices of this account's own that have something waiting here. */
  markAsked: async (deviceIds: string[]): Promise<void> => {
    if (deviceIds.length === 0) return;
    await update<PeerKeyChange[]>(PEER_CHANGES, (existing) =>
      existing?.map((change) =>
        deviceIds.includes(change.deviceId) ? { ...change, asked: true as const } : change
      )
    );
  },
  /**
   * The person has dealt with these devices: the keys are already remembered,
   * and this clears their holds. A compared safety number is recorded with it,
   * in the same transaction, so the two never disagree about what was checked.
   */
  acknowledge: async (
    deviceIds: string[],
    pair?: { userId: number; number: string }
  ): Promise<void> => {
    await updatePair<PeerKeyChange[], Record<number, string>>(
      PEER_CHANGES,
      VERIFIED_PAIRS,
      (held, verified) => ({
        a: (held ?? []).filter((change) => !deviceIds.includes(change.deviceId)),
        b: pair ? { ...verified, [pair.userId]: pair.number } : undefined,
      })
    );
  },
};

/**
 * The safety number last compared with each person, by their user id. A pair
 * reads as verified while their number still matches it; any change to their
 * devices changes the number.
 */
export const verifiedPairs = {
  get: async (userId: number): Promise<string | undefined> =>
    (await read<Record<number, string>>(VERIFIED_PAIRS))?.[userId],
};

/**
 * A history request from a confirmed device of this account's, waiting to be
 * served or declined as the person answered when they confirmed it.
 *
 * One at a time: a second device asking while the first is waiting replaces it.
 */
export interface HistoryRequest {
  requestId: string;
  deviceId: string;
  fingerprint: string;
  at: string;
}

export const pendingHistoryRequest = {
  get: () => read<HistoryRequest>("history-pending"),
  set: (request: HistoryRequest) => write("history-pending", request),
  clear: () => write("history-pending", undefined),
};

/**
 * How far this device has got sending its history to another.
 *
 * Sender-side, because the sender is what stops: a tab closed mid-transfer is
 * the failure this is for, and the queue holds what was already sent until the
 * far device collects it. Keyed by request, so an answer to an older request
 * cannot advance a newer one.
 */
export interface HistoryProgress {
  requestId: string;
  /** Conversations already sent in full. */
  done: string[];
  seq: number;
}

export const historyProgress = {
  get: (deviceId: string) => read<HistoryProgress>("history-progress:" + deviceId),
  set: (deviceId: string, progress: HistoryProgress) =>
    write("history-progress:" + deviceId, progress),
};

/**
 * The request this device sent for its own history, while it is outstanding.
 *
 * Asked once, and answered once: `"closed"` records that the question has been
 * settled — by a transfer finishing, or by a device saying no — and is what
 * tells later arrivals they answer nothing that was asked.
 *
 * `asked` names the devices it went to, which are the only ones an answer is
 * taken from. `at` is when it was asked, which is what lets the notice about it
 * stop being shown long before the question itself stops being worth answering.
 *
 * `"eligible"` is a device that arrived empty and has not got its question out
 * yet. It is written at registration rather than worked out later, because the
 * only moment that can tell a device which arrived with nothing from one that
 * has everything is the moment it came into being — a log with a message in it
 * says nothing about which of the two this is.
 */
export type HistoryAsk =
  | { requestId: string; asked?: string[]; at?: string; dismissed?: true }
  | "eligible"
  | "closed";

export const historyAsk = {
  get: () => read<HistoryAsk>("history-ask"),
  eligible: () => write("history-ask", "eligible"),
  open: (requestId: string, asked: string[]) =>
    write("history-ask", { requestId, asked, at: new Date().toISOString() }),
  close: () => write("history-ask", "closed"),
  /**
   * Take the notice down without answering the question.
   *
   * Deliberately not `close()`. The request id is what an arriving transfer is
   * matched against, so closing here would mean somebody who put the notice
   * away, walked to their other device and approved it would have the history
   * arrive and be discarded. The ask stays outstanding; only the banner stops.
   *
   * Read-modify-write rather than a plain put: an answer can land in another
   * tab at the same moment, and a dismissal must not resurrect an ask that has
   * just been settled.
   */
  dismissNotice: async (): Promise<void> => {
    await update<HistoryAsk>("history-ask", (current) =>
      typeof current === "object" ? { ...current, dismissed: true } : undefined
    );
  },
};

/**
 * A conversation this device has just joined and has yet to be caught up on.
 *
 * Only a group ever has one. A pair does not exist until both sides have
 * agreed, so there is never anything said before you were there.
 */
export interface ThreadCatchUp {
  /** What an arriving transfer is matched against. */
  requestId: string;
  /** The members still sending, once asked. Absent until the ask goes out. */
  waiting?: number[];
  /** When the ask went out, so a member who never answers is closed after a while. */
  at: string;
}

/**
 * The conversations waiting to be caught up on, all in one record.
 *
 * One key rather than one per conversation: every collection reads the whole
 * set to decide whether anything is outstanding, and a key scan to answer
 * "anything?" is a scan of every thread this device holds.
 */
export const threadCatchUp = {
  all: async (): Promise<Record<string, ThreadCatchUp>> =>
    (await read<Record<string, ThreadCatchUp>>("thread-catch-ups")) ?? {},
  get: async (conversationId: string): Promise<ThreadCatchUp | undefined> =>
    (await threadCatchUp.all())[conversationId],
  /**
   * Read-modify-write, like every other record two tabs can reach: a
   * collection in one tab and an answer in another both land here.
   */
  set: async (conversationId: string, state: ThreadCatchUp): Promise<void> => {
    await update<Record<string, ThreadCatchUp>>("thread-catch-ups", (current) => ({
      ...(current ?? {}),
      [conversationId]: state,
    }));
  },
  clear: async (conversationId: string): Promise<void> => {
    await update<Record<string, ThreadCatchUp>>("thread-catch-ups", (current) => {
      if (!current || !(conversationId in current)) return undefined;
      const { [conversationId]: _gone, ...rest } = current;
      return rest;
    });
  },
  /** One member has sent all of theirs; the ask closes with the last of them. */
  answered: async (conversationId: string, userId: number): Promise<void> => {
    await update<Record<string, ThreadCatchUp>>("thread-catch-ups", (current) => {
      const state = current?.[conversationId];
      if (!current || !state) return undefined;
      const waiting = (state.waiting ?? []).filter((member) => member !== userId);
      if (waiting.length > 0) return { ...current, [conversationId]: { ...state, waiting } };
      const { [conversationId]: _done, ...rest } = current;
      return rest;
    });
  },
};

/** Which device of theirs we already hold a session with, per session id. */
export const sessionForDevice = {
  get: (deviceId: string) => read<string>("device-session:" + deviceId),
  set: (deviceId: string, sessionId: string) => write("device-session:" + deviceId, sessionId),
  /**
   * Stop using the session filed against a device.
   *
   * Sessions are filed by device id, and a device id outlives the key it was
   * opened against. When the directory returns a different key for a device
   * this browser has already spoken to, the session in hand was negotiated
   * with the previous one and the far end can no longer read anything sent
   * through it — so the next send has to start a new one.
   *
   * The pickle itself is left where it is. Other conversations file the same
   * session id, and deleting it out from under them is a wider change than
   * this needs; dropping the pointer is enough to stop it being chosen.
   */
  forget: (deviceId: string) => write("device-session:" + deviceId, undefined),
};

/**
 * Every session this device holds inside one conversation.
 *
 * A list rather than a single id: the other party may have several devices, and
 * each is its own ratchet. An ordinary message names none of them, so decrypting
 * one means trying the sessions this conversation has — a handful, at most.
 */
export const sessionsInConversation = {
  get: async (conversationId: string): Promise<string[]> =>
    (await read<string[]>("conversation-sessions:" + conversationId)) ?? [],
  add: async (conversationId: string, sessionId: string): Promise<void> => {
    await update<string[]>("conversation-sessions:" + conversationId, (existing) => {
      const current = existing ?? [];
      if (current.includes(sessionId)) return undefined;
      // Most recent first: the session a message just arrived on is the one the
      // next message is most likely to be on.
      return [sessionId, ...current];
    });
  },
};

/**
 * Whose device is on the other end of a session.
 *
 * A message arriving from this account's own other client is the sender's own
 * outbox catching up, and belongs on the sender's side of the thread. The queue
 * row says nothing about who wrote it, so this is recorded when the session is
 * established — which is the only moment either end is known.
 */
export type SessionOrigin = "self" | "other";

export const sessionOrigin = {
  get: (id: string) => read<SessionOrigin>("session-origin:" + id),
  set: (id: string, origin: SessionOrigin) => write("session-origin:" + id, origin),
};

/**
 * Which account a session belongs to, recorded when it is established.
 *
 * "Their side" is one person in a pair and several in a group, so the side an
 * envelope arrived on stops being enough to say who sent it. A session is with
 * exactly one device, which belongs to exactly one account, and that is settled
 * the moment the session is opened -- an ordinary message arriving on it later
 * names no sender.
 *
 * Absent on sessions opened before this was recorded, which are all pairwise.
 */
export const sessionAuthor = {
  get: (id: string) => read<number>("session-author:" + id),
  set: (id: string, userId: number) => write("session-author:" + id, userId),
};

/**
 * Which device is on the other end of a session, recorded when it is opened.
 * Absent on sessions opened before this was recorded.
 */
export const sessionDevice = {
  get: (id: string) => read<string>("session-device:" + id),
  set: (id: string, deviceId: string) => write("session-device:" + id, deviceId),
};

/**
 * Every session this device holds, most recent first.
 *
 * The per-conversation list above is where an ordinary message is looked up,
 * and it is not always enough: one device is in every conversation this account
 * has — its own other clients are — so a session opened in one conversation can
 * carry a message in another. This is where collection looks when the
 * conversation's own list does not answer, and what it finds is filed there.
 */
export const allSessions = {
  get: async (): Promise<string[]> => (await read<string[]>("all-sessions")) ?? [],
  add: async (sessionId: string): Promise<void> => {
    await update<string[]>("all-sessions", (existing) => {
      const current = existing ?? [];
      if (current.includes(sessionId)) return undefined;
      return [sessionId, ...current];
    });
  },
};

export const sessionPickle = {
  get: (id: string) => read<string>(SESSION_PREFIX + id),
  set: (id: string, pickle: string) => write(SESSION_PREFIX + id, pickle),
  /**
   * Advance a session only if it is still where the caller found it.
   *
   * A session moves on with every message it carries, and both ends have to
   * move together. Two tabs encrypting from the same point produce two messages
   * that claim the same place in the conversation, and the far end can only
   * open one of them.
   */
  swap: async (id: string, expected: string, next: string): Promise<boolean> => {
    const { written } = await update<string>(SESSION_PREFIX + id, (current) =>
      current === expected ? next : undefined
    );
    return written;
  },
};

/**
 * Forget everything on this device.
 *
 * What sign-out calls on the web, unless the person asked to be remembered. The
 * wrapping key belongs to this browser profile, so the store only ever means
 * anything on this machine. Losing history is the right outcome on a shared
 * computer and a surprise on a private one, which is why it is a choice offered
 * at sign-out rather than a setting.
 */
export async function forgetDevice(): Promise<void> {
  await drop();
}
