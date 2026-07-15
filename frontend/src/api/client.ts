import { Capacitor } from "@capacitor/core";
import axios, { type AxiosRequestConfig } from "axios";

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
// Tracks whether we currently believe a user session is active. On web the
// in-memory authToken is never set after a page reload (cookie auth is
// HttpOnly, so there's nothing for JS to restore). The 401 interceptor used
// to gate on `authToken` being set, which meant expired-cookie 401s were
// silently swallowed for reloaded tabs — the user had to manually refresh
// again to land on /welcome. An explicit session flag closes that gap.
let hasActiveSession = false;

/**
 * Set the authentication token.
 * @param token The token value (JWT or device token)
 * @param deviceToken If true, use "DeviceToken" auth scheme instead of "Bearer"
 */
export const setAuthToken = (token: string | null, deviceToken = false) => {
  authToken = token;
  isDeviceToken = deviceToken;
};

export const getAuthToken = (): string | null => authToken;

export const setHasActiveSession = (value: boolean) => {
  hasActiveSession = value;
};

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // Send cookies for web sessions (HttpOnly cookie auth).
  // Disabled on native: Capacitor uses Bearer/DeviceToken headers and the
  // backend returns Access-Control-Allow-Origin: * which is incompatible
  // with credentialed requests per the CORS spec.
  withCredentials: !Capacitor.isNativePlatform(),
  paramsSerializer: (params) => {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === undefined) continue;
      if (Array.isArray(value)) {
        if (value.length > 0 && typeof value[0] === "object") {
          // Arrays of objects (e.g. FilterCondition[]) → JSON string
          searchParams.append(key, JSON.stringify(value));
        } else {
          // Primitive arrays → repeated key format (key=1&key=2)
          value.forEach((v) => {
            searchParams.append(key, String(v));
          });
        }
      } else {
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
  return config;
});

const emitUnauthorized = () => {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
  }
};

// Silent session renewal (web only). An expired access cookie is renewable:
// the HttpOnly refresh cookie issued at login rotates into a fresh session via
// POST /auth/refresh, so a 401 gets one renewal attempt and a retry before it
// is surfaced as a signed-out state. Concurrent 401s share a single in-flight
// refresh. Native is excluded: it authenticates with device tokens and no
// refresh cookie exists there yet.
let refreshInFlight: Promise<boolean> | null = null;

const attemptSessionRefresh = (): Promise<boolean> => {
  if (!refreshInFlight) {
    refreshInFlight = apiClient
      .post<{ access_token: string }>("/auth/refresh")
      .then((response) => {
        // A Bearer token held in memory (web keeps one until reload) must
        // follow the rotation — the retried request would otherwise resend the
        // stale header, which the backend reads before the fresh cookie.
        if (authToken && !isDeviceToken && response.data?.access_token) {
          setAuthToken(response.data.access_token);
        }
        return true;
      })
      .catch(() => {
        // Surfacing the signed-out state lives HERE, not with the callers:
        // however many concurrent 401s share this renewal, the event fires
        // exactly once per failed attempt.
        if (hasActiveSession) {
          emitUnauthorized();
        }
        return false;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

// Auth lifecycle endpoints must not trigger a renewal: /auth/refresh itself
// (recursion), and login/logout, whose 401s mean something other than "the
// access token expired mid-session".
const isAuthLifecyclePath = (url: string | undefined): boolean =>
  !!url && /\/auth\/(token|refresh|logout|device-token)(\?|$)/.test(url);

interface RetriableRequestConfig extends AxiosRequestConfig {
  _sessionRefreshRetried?: boolean;
}

// Guild context lives in the request URL (/g/{guildId}/…), per tab — there is
// no ambient guild context to guard a response against, so the only response
// concern left is an expired session: try a silent renewal, then surface it.
apiClient.interceptors.response.use(undefined, async (error) => {
  const config = error.config as RetriableRequestConfig | undefined;
  if (
    error.response?.status === 401 &&
    !Capacitor.isNativePlatform() &&
    config &&
    !config._sessionRefreshRetried &&
    !isAuthLifecyclePath(config.url)
  ) {
    if (await attemptSessionRefresh()) {
      config._sessionRefreshRetried = true;
      return apiClient(config);
    }
    // The failed renewal already surfaced the signed-out state (once, from
    // the shared attempt) — just hand the original rejection back.
    return Promise.reject(error);
  }
  // 401s that never entered renewal: a retried request that 401'd again, and
  // native. Lifecycle 401s stay silent — a login/logout 401 is the caller's
  // to handle, not a session expiry.
  if (error.response?.status === 401 && hasActiveSession && !isAuthLifecyclePath(config?.url)) {
    emitUnauthorized();
  }
  return Promise.reject(error);
});
