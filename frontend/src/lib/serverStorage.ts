import { CREDENTIAL_KEYS, getItem, removeItem, setItem } from "@/lib/storage";

const SERVER_URL_KEY = "initiative-server-url";
// The self-hosted address as the person typed it. Kept through disconnecting,
// so their server is already filled in when they come back to it.
const SELF_HOSTED_ADDRESS_KEY = "initiative-self-hosted-address";

// Server URL storage
export function getStoredServerUrl(): string | null {
  return getItem(SERVER_URL_KEY);
}

export function setStoredServerUrl(url: string): void {
  setItem(SERVER_URL_KEY, url);
}

export function getSelfHostedAddress(): string | null {
  return getItem(SELF_HOSTED_ADDRESS_KEY);
}

export function setSelfHostedAddress(address: string): void {
  setItem(SELF_HOSTED_ADDRESS_KEY, address);
}

export function clearStoredServerUrl(): void {
  removeItem(SERVER_URL_KEY);
}

export function clearStoredToken(): void {
  removeItem(CREDENTIAL_KEYS.token);
}

// Clear all app data (for disconnect/logout)
export function clearAllStorage(): void {
  clearStoredServerUrl();
  clearStoredToken();
}
