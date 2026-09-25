/**
 * The shapes the ratchet hands back. These mirror the Rust structs in
 * `crypto/src/lib.rs`; the WASM boundary is untyped (`any`), so this is where
 * the types are asserted once rather than at every call site.
 */

/** A published key, signed by the device that published it. */
export interface PublishedKey {
  key_id: string;
  public_key: string;
  signature: string;
}

export interface AccountCreated {
  pickle: string;
  identity_key: string;
  fingerprint_key: string;
}

export interface KeysGenerated {
  pickle: string;
  one_time_keys: PublishedKey[];
  fallback_key: PublishedKey | null;
}

export interface OutboundSession {
  session_pickle: string;
  session_id: string;
}

/** Which session a pre-key message opens, and the identity that sent it. */
export interface PreKeyInspected {
  session_id: string;
  identity_key: string;
}

export interface InboundSession {
  account_pickle: string;
  session_pickle: string;
  session_id: string;
  plaintext: string;
}

export interface Encrypted {
  session_pickle: string;
  message_type: number;
  ciphertext: string;
}

export interface Decrypted {
  session_pickle: string;
  plaintext: string;
}
