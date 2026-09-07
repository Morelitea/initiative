//! Olm double-ratchet bindings for Initiative's direct messages.
//!
//! This crate contains no cryptography of its own. It is an ergonomics and
//! serialisation shim over [`vodozemac`], which is the audited Rust
//! implementation of the Olm and Megolm ratchets — we take only Olm, because
//! direct messages are one-to-one and Megolm exists to make group messaging
//! cheap.
//!
//! **State lives in TypeScript, not here.** Every entry point takes the pickles
//! it needs and hands new ones back, so the caller decides where they are
//! stored and nothing is retained across a call. A pickle is already encrypted
//! by vodozemac under a 32-byte key the caller supplies, which is the only
//! secret the platform layer has to protect.
//!
//! One WebAssembly artifact serves the browser and both native apps, because
//! Capacitor runs the same web bundle inside a WebView.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use vodozemac::{
    olm::{Account, AccountPickle, OlmMessage, Session, SessionConfig, SessionPickle},
    Curve25519PublicKey,
};
use wasm_bindgen::prelude::*;

/// A published key, as the directory carries it.
#[derive(Serialize, Deserialize)]
pub struct PublishedKey {
    pub key_id: String,
    pub public_key: String,
}

#[derive(Serialize)]
pub struct AccountCreated {
    pub pickle: String,
    pub identity_key: String,
    pub fingerprint_key: String,
}

#[derive(Serialize)]
pub struct KeysGenerated {
    pub pickle: String,
    pub one_time_keys: Vec<PublishedKey>,
    pub fallback_key: Option<PublishedKey>,
}

#[derive(Serialize)]
pub struct OutboundSession {
    pub session_pickle: String,
    pub session_id: String,
}

#[derive(Serialize)]
pub struct InboundSession {
    pub account_pickle: String,
    pub session_pickle: String,
    pub session_id: String,
    pub plaintext: String,
}

#[derive(Serialize)]
pub struct Encrypted {
    pub session_pickle: String,
    pub message_type: u8,
    pub ciphertext: String,
}

#[derive(Serialize)]
pub struct Decrypted {
    pub session_pickle: String,
    pub plaintext: String,
}

fn pickle_key(encoded: &str) -> Result<[u8; 32], JsError> {
    let raw = base64_decode(encoded)?;
    raw.try_into()
        .map_err(|_| JsError::new("pickle key must be 32 bytes"))
}

fn base64_decode(encoded: &str) -> Result<Vec<u8>, JsError> {
    use base64::Engine as _;
    base64::engine::general_purpose::STANDARD
        .decode(encoded)
        .map_err(|_| JsError::new("expected base64"))
}

fn base64_encode(raw: &[u8]) -> String {
    use base64::Engine as _;
    base64::engine::general_purpose::STANDARD.encode(raw)
}

fn load_account(pickle: &str, key: &str) -> Result<Account, JsError> {
    let key = pickle_key(key)?;
    let pickle = AccountPickle::from_encrypted(pickle, &key)
        .map_err(|_| JsError::new("could not read the account key store"))?;
    Ok(Account::from_pickle(pickle))
}

fn save_account(account: &Account, key: &str) -> Result<String, JsError> {
    Ok(account.pickle().encrypt(&pickle_key(key)?))
}

fn load_session(pickle: &str, key: &str) -> Result<Session, JsError> {
    let key = pickle_key(key)?;
    let pickle = SessionPickle::from_encrypted(pickle, &key)
        .map_err(|_| JsError::new("could not read the session key store"))?;
    Ok(Session::from_pickle(pickle))
}

fn save_session(session: &Session, key: &str) -> Result<String, JsError> {
    Ok(session.pickle().encrypt(&pickle_key(key)?))
}

fn published(keys: HashMap<vodozemac::KeyId, Curve25519PublicKey>) -> Vec<PublishedKey> {
    let mut out: Vec<PublishedKey> = keys
        .into_iter()
        .map(|(id, key)| PublishedKey {
            key_id: id.to_base64(),
            public_key: key.to_base64(),
        })
        .collect();
    // A stable order so a caller comparing two runs sees the same list.
    out.sort_by(|a, b| a.key_id.cmp(&b.key_id));
    out
}

fn to_js<T: Serialize>(value: &T) -> Result<JsValue, JsError> {
    serde_wasm_bindgen::to_value(value).map_err(|error| JsError::new(&error.to_string()))
}

/// Generate this device's long-lived identity.
///
/// The private halves exist only inside the returned pickle, which is already
/// encrypted under `key`.
#[wasm_bindgen]
pub fn create_account(key: &str) -> Result<JsValue, JsError> {
    let account = Account::new();
    to_js(&AccountCreated {
        identity_key: account.curve25519_key().to_base64(),
        fingerprint_key: account.ed25519_key().to_base64(),
        pickle: save_account(&account, key)?,
    })
}

/// Top the prekey pool up, and mint a fallback key if asked.
///
/// The fallback key is reusable and is what a sender gets when the pool is
/// drained, so a device that has been quiet for a long time stays reachable.
#[wasm_bindgen]
pub fn generate_keys(
    pickle: &str,
    key: &str,
    count: usize,
    with_fallback: bool,
) -> Result<JsValue, JsError> {
    let mut account = load_account(pickle, key)?;
    account.generate_one_time_keys(count);
    let one_time_keys = published(account.one_time_keys());
    let fallback_key = if with_fallback {
        account.generate_fallback_key();
        published(account.fallback_key()).into_iter().next()
    } else {
        None
    };
    // Published means published: the account stops offering them again.
    account.mark_keys_as_published();
    to_js(&KeysGenerated {
        pickle: save_account(&account, key)?,
        one_time_keys,
        fallback_key,
    })
}

/// Open a session with a device, spending a prekey claimed from the directory.
#[wasm_bindgen]
pub fn create_outbound_session(
    pickle: &str,
    key: &str,
    their_identity_key: &str,
    their_one_time_key: &str,
) -> Result<JsValue, JsError> {
    let account = load_account(pickle, key)?;
    let identity = Curve25519PublicKey::from_base64(their_identity_key)
        .map_err(|_| JsError::new("bad identity key"))?;
    let one_time = Curve25519PublicKey::from_base64(their_one_time_key)
        .map_err(|_| JsError::new("bad one-time key"))?;
    let session = account.create_outbound_session(SessionConfig::version_2(), identity, one_time);
    to_js(&OutboundSession {
        session_id: session.session_id(),
        session_pickle: save_session(&session, key)?,
    })
}

/// Answer a pre-key message by deriving the session it describes.
///
/// The account changes too: the prekey it spent is forgotten, so the same
/// message cannot open a second session.
#[wasm_bindgen]
pub fn create_inbound_session(
    pickle: &str,
    key: &str,
    their_identity_key: &str,
    ciphertext: &str,
) -> Result<JsValue, JsError> {
    let mut account = load_account(pickle, key)?;
    let identity = Curve25519PublicKey::from_base64(their_identity_key)
        .map_err(|_| JsError::new("bad identity key"))?;
    let message = OlmMessage::from_parts(0, &base64_decode(ciphertext)?)
        .map_err(|_| JsError::new("not a pre-key message"))?;
    let OlmMessage::PreKey(prekey) = message else {
        return Err(JsError::new("not a pre-key message"));
    };
    let result = account
        .create_inbound_session(identity, &prekey)
        .map_err(|_| JsError::new("could not open the session"))?;
    to_js(&InboundSession {
        account_pickle: save_account(&account, key)?,
        session_id: result.session.session_id(),
        session_pickle: save_session(&result.session, key)?,
        plaintext: String::from_utf8_lossy(&result.plaintext).into_owned(),
    })
}

/// Encrypt one message, advancing the ratchet.
#[wasm_bindgen]
pub fn session_encrypt(pickle: &str, key: &str, plaintext: &str) -> Result<JsValue, JsError> {
    let mut session = load_session(pickle, key)?;
    let message = session.encrypt(plaintext);
    let (message_type, body) = message.to_parts();
    to_js(&Encrypted {
        session_pickle: save_session(&session, key)?,
        message_type: message_type as u8,
        ciphertext: base64_encode(&body),
    })
}

/// Decrypt one message, advancing the ratchet.
#[wasm_bindgen]
pub fn session_decrypt(
    pickle: &str,
    key: &str,
    message_type: u8,
    ciphertext: &str,
) -> Result<JsValue, JsError> {
    let mut session = load_session(pickle, key)?;
    let message = OlmMessage::from_parts(message_type as usize, &base64_decode(ciphertext)?)
        .map_err(|_| JsError::new("unreadable message"))?;
    let plaintext = session
        .decrypt(&message)
        .map_err(|_| JsError::new("could not decrypt"))?;
    to_js(&Decrypted {
        session_pickle: save_session(&session, key)?,
        plaintext: String::from_utf8_lossy(&plaintext).into_owned(),
    })
}
