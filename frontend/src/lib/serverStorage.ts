import { Capacitor } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";

const SERVER_URL_KEY = "initiative-server-url";
const TOKEN_KEY = "initiative-token";

/**
 * Storage abstraction that uses Capacitor Preferences on native platforms
 * and localStorage on web. Preferences is more reliable on mobile as
 * localStorage can be cleared by the OS when low on space.
 */

const isNative = Capacitor.isNativePlatform();

async function getValue(key: string): Promise<string | null> {
  if (isNative) {
    const { value } = await Preferences.get({ key });
    return value;
  }
  return localStorage.getItem(key);
}

async function setValue(key: string, value: string): Promise<void> {
  if (isNative) {
    await Preferences.set({ key, value });
  } else {
    localStorage.setItem(key, value);
  }
}

async function removeValue(key: string): Promise<void> {
  if (isNative) {
    await Preferences.remove({ key });
  } else {
    localStorage.removeItem(key);
  }
}

// Server URL storage
export async function getStoredServerUrl(): Promise<string | null> {
  return getValue(SERVER_URL_KEY);
}

export async function setStoredServerUrl(url: string): Promise<void> {
  return setValue(SERVER_URL_KEY, url);
}

export async function clearStoredServerUrl(): Promise<void> {
  return removeValue(SERVER_URL_KEY);
}

// Token storage (for mobile, we store device tokens in Preferences)
export async function getStoredToken(): Promise<string | null> {
  return getValue(TOKEN_KEY);
}

export async function setStoredToken(token: string): Promise<void> {
  return setValue(TOKEN_KEY, token);
}

export async function clearStoredToken(): Promise<void> {
  return removeValue(TOKEN_KEY);
}

// Clear all app data (for disconnect/logout)
export async function clearAllStorage(): Promise<void> {
  await clearStoredServerUrl();
  await clearStoredToken();
}
