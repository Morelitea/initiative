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

const DB_NAME = "initiative-dm";
const DB_VERSION = 1;
const STORE = "keys";
const WRAP_KEY = "wrap-key";
const PICKLE_KEY = "pickle-key";
const ACCOUNT = "account";
const DEVICE_ID = "device-id";
const SESSION_PREFIX = "session:";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
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

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
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
  | { status: "claiming"; at: number }
  | { status: "ready"; deviceId: string };

const DEVICE_CLAIM = "device-claim";
const CLAIM_STALE_MS = 30_000;

export const deviceClaim = {
  read: () => read<DeviceClaim>(DEVICE_CLAIM),

  /** True if this caller may register. False means somebody else is on it. */
  take: async (): Promise<boolean> => {
    const now = Date.now();
    const { written } = await update<DeviceClaim>(DEVICE_CLAIM, (current) => {
      if (current?.status === "ready") return undefined;
      if (current?.status === "claiming" && now - current.at < CLAIM_STALE_MS) {
        return undefined;
      }
      return { status: "claiming", at: now };
    });
    return written;
  },

  settle: async (deviceId: string): Promise<void> => {
    await update<DeviceClaim>(DEVICE_CLAIM, () => ({ status: "ready", deviceId }));
  },

  /** Force the claim open again — the recorded device is gone from the server. */
  invalidate: async (): Promise<void> => {
    await update<DeviceClaim>(DEVICE_CLAIM, () => ({ status: "claiming", at: 0 }));
  },

  /** Let go of a claim this caller could not finish. */
  release: async (): Promise<void> => {
    await update<DeviceClaim>(DEVICE_CLAIM, (current) =>
      current?.status === "claiming" ? { status: "claiming", at: 0 } : undefined
    );
  },
};

export const accountPickle = {
  get: () => read<string>(ACCOUNT),
  set: (pickle: string) => write(ACCOUNT, pickle),
};

export const deviceId = {
  get: () => read<string>(DEVICE_ID),
  set: (id: string) => write(DEVICE_ID, id),
};

/**
 * What this device has read, per conversation.
 *
 * The client is the archive: the server deletes a message the moment it is
 * collected, so if this is not written down the message is gone. Kept beside
 * the ratchet rather than in React state for the same reason.
 */
export interface StoredMessage {
  id: string;
  body: string;
  at: string;
  mine: boolean;
}

const LOG_PREFIX = "log:";

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
};

/** Which device of theirs we already hold a session with, per session id. */
export const sessionForDevice = {
  get: (deviceId: string) => read<string>("device-session:" + deviceId),
  set: (deviceId: string, sessionId: string) => write("device-session:" + deviceId, sessionId),
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

export const sessionPickle = {
  get: (id: string) => read<string>(SESSION_PREFIX + id),
  set: (id: string, pickle: string) => write(SESSION_PREFIX + id, pickle),
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

export { fromBase64, toBase64 };
