/**
 * The ratchet itself, as it runs inside the worker.
 *
 * Nothing here holds state between calls: every entry point takes the pickles
 * it needs and returns new ones. Those pickles are ciphertext, which is why the
 * main thread may hold them.
 *
 * **The pickle key is fetched here, not passed in.** It is the one secret that
 * opens a pickle, and this module runs inside the worker — so the key is read
 * from the store on this side and never crosses a `postMessage`.
 */

import { pickleKey } from "./store";
import type {
  AccountCreated,
  Decrypted,
  Encrypted,
  InboundSession,
  KeysGenerated,
  OutboundSession,
} from "./types";
import init, {
  create_account,
  create_inbound_session,
  create_outbound_session,
  generate_keys,
  session_decrypt,
  session_encrypt,
} from "./wasm/initiative_ratchet.js";

let ready: Promise<unknown> | null = null;

const isNode = typeof process !== "undefined" && process.versions?.node !== undefined;

/**
 * Load the WebAssembly module once per context.
 *
 * In a browser the generated glue fetches the `.wasm` beside itself. Node has
 * nothing to fetch it from, so the bytes are read off disk and handed over —
 * which is only the test environment.
 */
export function loadRatchet(): Promise<unknown> {
  if (ready === null) {
    ready = isNode ? initFromDisk() : init();
  }
  return ready;
}

async function initFromDisk(): Promise<unknown> {
  const { readFile } = await import("node:fs/promises");
  const { resolve } = await import("node:path");
  // Resolved from the working directory rather than `import.meta.url`: under
  // the test runner that is an http: URL, which has no path to read.
  const path = resolve(process.cwd(), "src/crypto/wasm/initiative_ratchet_bg.wasm");
  return init({ module_or_path: await readFile(path) });
}

export async function createAccount(): Promise<AccountCreated> {
  await loadRatchet();
  return create_account(await pickleKey()) as AccountCreated;
}

export async function generateKeys(
  pickle: string,
  count: number,
  withFallback: boolean
): Promise<KeysGenerated> {
  await loadRatchet();
  return generate_keys(pickle, await pickleKey(), count, withFallback) as KeysGenerated;
}

export async function createOutboundSession(
  pickle: string,
  theirIdentityKey: string,
  theirOneTimeKey: string
): Promise<OutboundSession> {
  await loadRatchet();
  return create_outbound_session(
    pickle,
    await pickleKey(),
    theirIdentityKey,
    theirOneTimeKey
  ) as OutboundSession;
}

export async function createInboundSession(
  pickle: string,
  theirIdentityKey: string,
  ciphertext: string
): Promise<InboundSession> {
  await loadRatchet();
  return create_inbound_session(
    pickle,
    await pickleKey(),
    theirIdentityKey,
    ciphertext
  ) as InboundSession;
}

export async function encrypt(sessionPickle: string, plaintext: string): Promise<Encrypted> {
  await loadRatchet();
  return session_encrypt(sessionPickle, await pickleKey(), plaintext) as Encrypted;
}

export async function decrypt(
  sessionPickle: string,
  messageType: number,
  ciphertext: string
): Promise<Decrypted> {
  await loadRatchet();
  return session_decrypt(sessionPickle, await pickleKey(), messageType, ciphertext) as Decrypted;
}
