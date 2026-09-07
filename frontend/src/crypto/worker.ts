/**
 * The worker the ratchet runs in.
 *
 * Key material stays in this context: the main thread posts a request and
 * receives a result, and the pickles it holds are ciphertext it cannot open
 * without the pickle key, which never leaves here either.
 */

import {
  createAccount,
  createInboundSession,
  createOutboundSession,
  decrypt,
  encrypt,
  generateKeys,
} from "./engine";

/** The only calls the worker will make. Not every export of `engine`. */
const methods = {
  createAccount,
  generateKeys,
  createOutboundSession,
  createInboundSession,
  encrypt,
  decrypt,
} as const;

export type RatchetMethod = keyof typeof methods;

type Call = {
  id: number;
  method: RatchetMethod;
  args: unknown[];
};

self.onmessage = async (event: MessageEvent<Call>) => {
  const { id, method, args } = event.data;
  try {
    const fn = methods[method] as (...a: unknown[]) => Promise<unknown>;
    if (typeof fn !== "function") {
      throw new Error(`unknown ratchet call: ${String(method)}`);
    }
    const result = await fn(...args);
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({
      id,
      error: error instanceof Error ? error.message : String(error),
    });
  }
};
