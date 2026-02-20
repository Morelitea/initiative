import { Capacitor } from "@capacitor/core";
import axios from "axios";

const DEFAULT_API_BASE_URL = "/api/v1";
const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"]);

/**
 * Resolve the initial API base URL.
 * On native platforms, we return a placeholder - the actual URL
 * will be set by the ServerProvider after loading from storage.
 */
const resolveApiBaseUrl = (): string => {
  const envValue = import.meta.env.VITE_API_URL?.trim();
  const isNative = Capacitor.isNativePlatform();

  // On native, the URL will be set dynamically by ServerProvider
  // We use a placeholder that will fail if used before configuration
  if (isNative) {
    // If env value is set (for dev/testing), use it as initial value
    if (envValue) {
      return envValue;
    }
    return ""; // Will be set by ServerProvider
  }

  if (!envValue) {
    return DEFAULT_API_BASE_URL;
  }

  if (typeof window === "undefined") {
    return envValue;
  }

  try {
    const resolved = new URL(envValue, window.location.origin);
    const envIsLocalhost = LOCAL_HOSTNAMES.has(resolved.hostname.toLowerCase());
    const browserIsLocalhost = LOCAL_HOSTNAMES.has(window.location.hostname.toLowerCase());

    if (envIsLocalhost && !browserIsLocalhost) {
      // Avoid leaking localhost API URLs when the SPA is served from a remote host.
      return DEFAULT_API_BASE_URL;
    }

    if (resolved.origin === window.location.origin) {
      return `${resolved.pathname}${resolved.search}` || DEFAULT_API_BASE_URL;
    }

    return resolved.toString();
  } catch {
    if (envValue.startsWith("/")) {
      return envValue;
    }
  }

  return DEFAULT_API_BASE_URL;
};

export let API_BASE_URL = resolveApiBaseUrl();

/**
 * Dynamically update the API base URL.
 * Used by ServerProvider on native platforms to set the user-configured server URL.
 */
export const setApiBaseUrl = (url: string) => {
  API_BASE_URL = url;
  apiClient.defaults.baseURL = url;
};

export const AUTH_UNAUTHORIZED_EVENT = "initiative:auth:unauthorized";

let authToken: string | null = null;
let isDeviceToken = false;
let activeGuildId: number | null = null;

/**
 * Set the authentication token.
 * @param token The token value (JWT or device token)
 * @param deviceToken If true, use "DeviceToken" auth scheme instead of "Bearer"
 */
export const setAuthToken = (token: string | null, deviceToken = false) => {
  authToken = token;
  isDeviceToken = deviceToken;
};

export const setCurrentGuildId = (guildId: number | null) => {
  activeGuildId = guildId;
};

export const getCurrentGuildId = () => activeGuildId;

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  paramsSerializer: (params) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (Array.isArray(value)) {
        // For arrays, add each value with the same key (repeat format)
        value.forEach((v) => searchParams.append(key, String(v)));
      } else if (value !== null && value !== undefined) {
        searchParams.append(key, String(value));
      }
    }
    return searchParams.toString();
  },
});

apiClient.interceptors.request.use((config) => {
  if (authToken) {
    config.headers = config.headers ?? {};
    // Use DeviceToken scheme for device tokens, Bearer for JWTs
    const scheme = isDeviceToken ? "DeviceToken" : "Bearer";
    config.headers.Authorization = `${scheme} ${authToken}`;
  }
  if (activeGuildId !== null) {
    config.headers = config.headers ?? {};
    const hasCustomGuildHeader = Object.keys(config.headers).some(
      (key) => key.toLowerCase() === "x-guild-id"
    );
    if (!hasCustomGuildHeader) {
      config.headers["X-Guild-ID"] = String(activeGuildId);
    }
  }
  return config;
});

const emitUnauthorized = () => {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
  }
};

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && authToken) {
      emitUnauthorized();
    }
    return Promise.reject(error);
  }
);
