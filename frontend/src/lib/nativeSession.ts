/**
 * The refresh token the native app keeps.
 *
 * The app holds a session the way the browser does: a short-lived access token
 * plus a refresh token that is replaced each time it is used, so a copy taken
 * from a backup is spent the moment the app renews. The browser's refresh token
 * is an HttpOnly cookie; the app has no cookie jar, so it keeps its own here
 * and hands it over in the body of a renewal.
 *
 * Where it is kept: the app's credential store, which its Android backup rules
 * leave out (see `CREDENTIAL_KEYS`). Moving it to the platform keychain is a
 * separate change, and a native release.
 */
import { CREDENTIAL_KEYS, getItem, removeItem, setItem } from "@/lib/storage";

/** What a native sign-in hands back. */
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
