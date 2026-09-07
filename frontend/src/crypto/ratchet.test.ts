/**
 * The ratchet, end to end.
 *
 * This is the test that matters for the whole feature: two accounts that have
 * never met derive a shared session from published keys alone, and what one
 * sends the other can read. If this passes, the server is carrying bytes it
 * cannot open.
 */

import { describe, expect, it, vi } from "vitest";

// The worker reads the pickle key from the store on its own side, and there is
// no IndexedDB here — so the store is stubbed with a fixed key. The ratchet
// under test is entirely real.
vi.mock("./store", () => ({
  pickleKey: async () => btoa(String.fromCharCode(...new Uint8Array(32).fill(7))),
}));

// The engine, not the client: the client only speaks to a worker, and what is
// under test here is the ratchet rather than the transport that reaches it.
import * as ratchet from "./engine";

describe("the double ratchet", () => {
  it("carries a message between two accounts that never exchanged a secret", async () => {
    const alice = await ratchet.createAccount();
    const bob = await ratchet.createAccount();

    // Bob publishes prekeys; Alice claims one from the directory.
    const bobKeys = await ratchet.generateKeys(bob.pickle, 5, true);
    const claimed = bobKeys.one_time_keys[0];

    const outbound = await ratchet.createOutboundSession(
      alice.pickle,
      bob.identity_key,
      claimed.public_key
    );
    const sent = await ratchet.encrypt(outbound.session_pickle, "the server cannot read this");
    expect(sent.message_type).toBe(0);

    const inbound = await ratchet.createInboundSession(
      bobKeys.pickle,
      alice.identity_key,
      sent.ciphertext
    );
    expect(inbound.plaintext).toBe("the server cannot read this");
  });

  it("keeps the conversation going after the session is established", async () => {
    const alice = await ratchet.createAccount();
    const bob = await ratchet.createAccount();
    const bobKeys = await ratchet.generateKeys(bob.pickle, 5, true);

    const outbound = await ratchet.createOutboundSession(
      alice.pickle,
      bob.identity_key,
      bobKeys.one_time_keys[0].public_key
    );
    const first = await ratchet.encrypt(outbound.session_pickle, "one");
    const inbound = await ratchet.createInboundSession(
      bobKeys.pickle,
      alice.identity_key,
      first.ciphertext
    );

    // Bob answers on the session the pre-key message established.
    const reply = await ratchet.encrypt(inbound.session_pickle, "two");
    const read = await ratchet.decrypt(first.session_pickle, reply.message_type, reply.ciphertext);
    expect(read.plaintext).toBe("two");
  });

  it("publishes a reusable fallback key alongside the pool", async () => {
    const account = await ratchet.createAccount();
    const keys = await ratchet.generateKeys(account.pickle, 3, true);

    expect(keys.one_time_keys).toHaveLength(3);
    expect(keys.fallback_key).not.toBeNull();
  });

  it("refuses a session pickle it cannot read", async () => {
    await expect(ratchet.decrypt("not-a-pickle", 1, "AAAA")).rejects.toThrow();
  });
});
