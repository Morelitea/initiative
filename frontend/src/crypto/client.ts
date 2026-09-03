/**
 * The ratchet, as the rest of the app calls it.
 *
 * Every call crosses into a dedicated worker so key material never enters the
 * main thread's heap — including the pickle key, which the worker reads from
 * the store itself rather than being handed. Where there is no `Worker` — Node, and therefore the test
 * suite — the same functions are called directly; that is a test-environment
 * fallback and not a browser code path, so the property holds everywhere it is
 * a property.
 */

import {
  createAccount,
  createInboundSession,
  createOutboundSession,
  decrypt,
  encrypt,
  generateKeys,
} from "./engine";
import type { RatchetMethod } from "./worker";

/** The same table the worker dispatches on, for the no-Worker fallback. */
const direct = {
  createAccount,
  generateKeys,
  createOutboundSession,
  createInboundSession,
  encrypt,
  decrypt,
} as const;

import type {
  AccountCreated,
  Decrypted,
  Encrypted,
  InboundSession,
  KeysGenerated,
  OutboundSession,
} from "./types";

type Pending = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
};

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, Pending>();

function ensureWorker(): Worker | null {
  if (typeof Worker === "undefined") return null;
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
  const instance = ensureWorker();
  if (instance === null) {
    const fn = direct[method] as (...a: unknown[]) => Promise<T>;
    return fn(...args);
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
