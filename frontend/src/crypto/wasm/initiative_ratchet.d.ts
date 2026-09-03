/* tslint:disable */
/* eslint-disable */

/**
 * Generate this device's long-lived identity.
 *
 * The private halves exist only inside the returned pickle, which is already
 * encrypted under `key`.
 */
export function create_account(key: string): any;

/**
 * Answer a pre-key message by deriving the session it describes.
 *
 * The account changes too: the prekey it spent is forgotten, so the same
 * message cannot open a second session.
 */
export function create_inbound_session(pickle: string, key: string, their_identity_key: string, ciphertext: string): any;

/**
 * Open a session with a device, spending a prekey claimed from the directory.
 */
export function create_outbound_session(pickle: string, key: string, their_identity_key: string, their_one_time_key: string): any;

/**
 * Top the prekey pool up, and mint a fallback key if asked.
 *
 * The fallback key is reusable and is what a sender gets when the pool is
 * drained, so a device that has been quiet for a long time stays reachable.
 */
export function generate_keys(pickle: string, key: string, count: number, with_fallback: boolean): any;

/**
 * Decrypt one message, advancing the ratchet.
 */
export function session_decrypt(pickle: string, key: string, message_type: number, ciphertext: string): any;

/**
 * Encrypt one message, advancing the ratchet.
 */
export function session_encrypt(pickle: string, key: string, plaintext: string): any;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly create_account: (a: number, b: number) => [number, number, number];
    readonly create_inbound_session: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number) => [number, number, number];
    readonly create_outbound_session: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number) => [number, number, number];
    readonly generate_keys: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number];
    readonly session_decrypt: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => [number, number, number];
    readonly session_encrypt: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number];
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
