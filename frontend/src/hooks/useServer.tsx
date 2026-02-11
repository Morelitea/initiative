import { ReactNode, createContext, useCallback, useContext, useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";

import { getStoredServerUrl, setStoredServerUrl, clearAllStorage } from "@/lib/serverStorage";
import { setApiBaseUrl } from "@/api/client";

interface ServerContextValue {
  /** The configured server URL (e.g., "https://myserver.com/api/v1") */
  serverUrl: string | null;
  /** Whether running on native platform (iOS/Android) */
  isNativePlatform: boolean;
  /** Whether a server URL is configured (always true on web) */
  isServerConfigured: boolean;
  /** Whether the provider is still loading */
  loading: boolean;
  /** Configure the server URL after validating it */
  setServerUrl: (url: string) => Promise<void>;
  /** Clear the server URL (disconnect from server) */
  clearServerUrl: () => Promise<void>;
  /** Test if a server URL is valid and reachable */
  testServerConnection: (url: string) => Promise<{ valid: boolean; error?: string }>;
  /** Get display-friendly hostname from server URL */
  getServerHostname: () => string | null;
}

const ServerContext = createContext<ServerContextValue | undefined>(undefined);

/**
 * Normalize a server URL to include /api/v1 suffix
 */
function normalizeServerUrl(url: string): string {
  let normalized = url.trim();

  // Add https:// if no protocol
  if (!normalized.startsWith("http://") && !normalized.startsWith("https://")) {
    normalized = "https://" + normalized;
  }

  // Remove trailing slashes
  normalized = normalized.replace(/\/+$/, "");

  // Remove /api/v1 if present (we'll add it back)
  normalized = normalized.replace(/\/api\/v1\/?$/, "");
  normalized = normalized.replace(/\/api\/?$/, "");

  // Add /api/v1
  normalized = normalized + "/api/v1";

  return normalized;
}

/**
 * Extract hostname from server URL for display
 */
function extractHostname(serverUrl: string): string | null {
  try {
    const url = new URL(serverUrl);
    return url.hostname;
  } catch {
    return null;
  }
}

export const ServerProvider = ({ children }: { children: ReactNode }) => {
  const [serverUrl, setServerUrlState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const isNativePlatform = Capacitor.isNativePlatform();

  // On web, server is always "configured" (uses relative URLs)
  // On native, we need an explicit server URL
  const isServerConfigured = !isNativePlatform || serverUrl !== null;

  // Load stored server URL on mount
  useEffect(() => {
    if (!isNativePlatform) {
      setLoading(false);
      return;
    }

    const stored = getStoredServerUrl();
    if (stored) {
      setServerUrlState(stored);
      setApiBaseUrl(stored);
    }
    setLoading(false);
  }, [isNativePlatform]);

  const testServerConnection = useCallback(
    async (url: string): Promise<{ valid: boolean; error?: string }> => {
      try {
        const normalizedUrl = normalizeServerUrl(url);

        // Test connectivity by fetching version endpoint
        const response = await fetch(`${normalizedUrl}/version`, {
          method: "GET",
          headers: { Accept: "application/json" },
        });

        if (!response.ok) {
          return { valid: false, error: `Server returned status ${response.status}` };
        }

        const data = await response.json();

        // Verify it's an Initiative server by checking response shape
        if (!data.version) {
          return { valid: false, error: "Not a valid Initiative server" };
        }

        return { valid: true };
      } catch (err) {
        console.error("Server connection test failed", err);
        if (err instanceof TypeError && err.message.includes("fetch")) {
          return { valid: false, error: "Could not connect to server" };
        }
        return { valid: false, error: "Connection failed" };
      }
    },
    []
  );

  const setServerUrl = useCallback(async (url: string): Promise<void> => {
    const normalizedUrl = normalizeServerUrl(url);
    setStoredServerUrl(normalizedUrl);
    setApiBaseUrl(normalizedUrl);
    setServerUrlState(normalizedUrl);
  }, []);

  const clearServerUrl = useCallback(async (): Promise<void> => {
    clearAllStorage();
    setServerUrlState(null);
  }, []);

  const getServerHostname = useCallback((): string | null => {
    if (!serverUrl) return null;
    return extractHostname(serverUrl);
  }, [serverUrl]);

  const value: ServerContextValue = {
    serverUrl,
    isNativePlatform,
    isServerConfigured,
    loading,
    setServerUrl,
    clearServerUrl,
    testServerConnection,
    getServerHostname,
  };

  return <ServerContext.Provider value={value}>{children}</ServerContext.Provider>;
};

export const useServer = () => {
  const context = useContext(ServerContext);
  if (!context) {
    throw new Error("useServer must be used within a ServerProvider");
  }
  return context;
};
