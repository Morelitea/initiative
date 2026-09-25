/**
 * The credential the native app prefers, and the way across from the old one.
 *
 * A device token is a single long-lived secret that the app sends on every
 * request for as long as it keeps working. A session is a short-lived access
 * token plus a refresh token that is replaced each time it is used, so a copy
 * taken from a backup is spent the moment the app renews. The app moves to one
 * without asking anybody to sign in again: it trades the token it already
 * holds, once, on the next launch.
 *
 * Nothing here strands anybody. A trade that fails leaves the device token
 * exactly as it was, and the app carries on with it — the backend serves both
 * for as long as it takes, and the schedule for retiring the old one is a
 * version floor, not a date.
 *
 * Where it is kept: the same store the device token has always used. A rotating
 * token that is replaced on every renewal is a smaller thing to leave there
 * than a fixed one lasting three months, so this is an improvement on its own,
 * and it is one that reaches an installed app over the air. Moving both to the
 * platform keychain is a separate change, and a native release.
 */
import { CREDENTIAL_KEYS, getItem, removeItem, setItem } from "@/lib/storage";

/** What a native sign-in or exchange hands back. */
export interface NativeSession {
  accessToken: string;
  refreshToken: string;
}

export const readRefreshToken = (): string | null => {
  try {
    return getItem(CREDENTIAL_KEYS.refreshToken);
  } catch {
    return null;
  }
};

export const storeRefreshToken = (token: string): void => {
  try {
    setItem(CREDENTIAL_KEYS.refreshToken, token);
  } catch {
    // Nothing persisted means the next launch signs in again, which is worse
    // than it was but not broken. Never worth failing the sign-in over.
  }
};

export const clearRefreshToken = (): void => {
  try {
    removeItem(CREDENTIAL_KEYS.refreshToken);
  } catch {
    // Same reasoning as above.
  }
};

/**
 * Read a session out of a response that may not carry one.
 *
 * A deployment that has not been updated answers a native sign-in with the
 * device token alone, so the fields are optional and their absence is the old
 * behaviour rather than an error.
 */
export const sessionFromResponse = (data: {
  access_token?: string | null;
  refresh_token?: string | null;
}): NativeSession | null =>
  data.access_token && data.refresh_token
    ? { accessToken: data.access_token, refreshToken: data.refresh_token }
    : null;
