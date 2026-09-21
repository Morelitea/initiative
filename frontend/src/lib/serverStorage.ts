import { getItem, removeItem, setItem } from "@/lib/storage";

const SERVER_URL_KEY = "initiative-server-url";
const TOKEN_KEY = "initiative-token";

// Server URL storage
export function getStoredServerUrl(): string | null {
  return getItem(SERVER_URL_KEY);
}

export function setStoredServerUrl(url: string): void {
  setItem(SERVER_URL_KEY, url);
}

export function clearStoredServerUrl(): void {
  removeItem(SERVER_URL_KEY);
}

export function clearStoredToken(): void {
  removeItem(TOKEN_KEY);
}

// Clear all app data (for disconnect/logout)
export function clearAllStorage(): void {
  clearStoredServerUrl();
  clearStoredToken();
}
