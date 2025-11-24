import axios from "axios";

const DEFAULT_API_BASE_URL = "/api/v1";
const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"]);

const resolveApiBaseUrl = (): string => {
  const envValue = import.meta.env.VITE_API_URL?.trim();
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

export const API_BASE_URL = resolveApiBaseUrl();

export const AUTH_UNAUTHORIZED_EVENT = "initiative:auth:unauthorized";

let authToken: string | null = null;

export const setAuthToken = (token: string | null) => {
  authToken = token;
};

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  if (authToken) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${authToken}`;
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
