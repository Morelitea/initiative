/**
 * The ratchet, as the rest of the app calls it.
 *
 * Every call crosses into a dedicated worker, and there is deliberately no path
 * that does not. Key material — including the pickle key, which the worker
 * reads from the store on its own side — therefore never enters the main
 * thread's realm.
 *
 * An earlier version fell back to calling the engine directly where `Worker`
 * was undefined. That is removed: a fallback is a second code path, and this
 * one would have held the key in exactly the realm the worker exists to keep it
 * out of. Somewhere without workers cannot have encrypted messages, and says so.
 *
 * Tests that exercise the ratchet itself import `./engine` directly.
 */

import type {
  AccountCreated,
  Decrypted,
  Encrypted,
  InboundSession,
  KeysGenerated,
  OutboundSession,
} from "./types";
import type { RatchetMethod } from "./worker";

type Pending = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
};

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, Pending>();

class RatchetUnavailableError extends Error {
  constructor() {
    super("encrypted messages need a browser that supports web workers");
    this.name = "RatchetUnavailableError";
  }
}

/**
 * Whether this runtime can hold a ratchet at all.
 *
 * Three things are needed and any of them can be missing: a worker to run the
 * ratchet in, somewhere to keep the key store, and the browser's own crypto —
 * which is only handed out on a secure origin, so a page served over plain
 * http from anything but localhost has none. That last one is the common one
 * in development, and it looks like a broken feature rather than a wrong
 * address unless it is said out loud.
 */
export function ratchetSupported(): boolean {
  return (
    typeof Worker !== "undefined" &&
    typeof indexedDB !== "undefined" &&
    typeof crypto !== "undefined" &&
    crypto.subtle !== undefined
  );
}

function ensureWorker(): Worker {
  if (typeof Worker === "undefined") throw new RatchetUnavailableError();
  if (worker === null) {
    worker = new Worker(new URL("./worker.ts", import.meta.url), {
      type: "module",
    });
    worker.onmessage = (event: MessageEvent<{ id: number; result?: unknown; error?: string }>) => {
      const entry = pending.get(event.data.id);
      if (!entry) return;
      pending.delete(event.data.id);
      if (event.data.error) entry.reject(new Error(event.data.error));
      else entry.resolve(event.data.result);
    };
  }
  return worker;
}

function call<T>(method: RatchetMethod, ...args: unknown[]): Promise<T> {
  let instance: Worker;
  try {
    instance = ensureWorker();
  } catch (error) {
    return Promise.reject(error);
  }
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
    instance.postMessage({ id, method, args });
  });
}

/**
 * The ratchet. No call takes a pickle key: the worker reads it on its own side,
 * so the one secret that opens a pickle never crosses a `postMessage`.
 */
export const ratchet = {
  createAccount: () => call<AccountCreated>("createAccount"),
  generateKeys: (pickle: string, count: number, withFallback: boolean) =>
    call<KeysGenerated>("generateKeys", pickle, count, withFallback),
  createOutboundSession: (pickle: string, theirIdentityKey: string, theirOneTimeKey: string) =>
    call<OutboundSession>("createOutboundSession", pickle, theirIdentityKey, theirOneTimeKey),
  createInboundSession: (pickle: string, theirIdentityKey: string, ciphertext: string) =>
    call<InboundSession>("createInboundSession", pickle, theirIdentityKey, ciphertext),
  encrypt: (sessionPickle: string, plaintext: string) =>
    call<Encrypted>("encrypt", sessionPickle, plaintext),
  decrypt: (sessionPickle: string, messageType: number, ciphertext: string) =>
    call<Decrypted>("decrypt", sessionPickle, messageType, ciphertext),
};
