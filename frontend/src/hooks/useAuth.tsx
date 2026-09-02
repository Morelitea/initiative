import { Capacitor } from "@capacitor/core";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  AUTH_UNAUTHORIZED_EVENT,
  apiClient,
  setAuthToken,
  setHasActiveSession,
} from "@/api/client";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { clearJustSignedIn, markJustSignedIn } from "@/lib/authTransition";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { queryClient } from "@/lib/queryClient";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { clearUploadToken } from "@/lib/uploadToken";

interface LoginPayload {
  email: string;
  password: string;
  deviceName?: string; // For mobile device token login
}

interface RegisterPayload {
  email: string;
  password: string;
  /** The name part of the handle. The number behind it is drawn server-side. */
  username: string;
  full_name?: string;
  inviteCode?: string;
  /** Optional IANA timezone name resolved from the browser at submit
   *  time. Forwarded so a new account starts at the user's wall clock
   *  instead of the backend default of "UTC". */
  timezone?: string;
  /** Optional captcha token from the rendered widget when the
   *  deployment has CAPTCHA_PROVIDER configured (see
   *  ``GET /api/v1/config``). Backend validates server-side; missing
   *  when the deployment has no captcha. */
  captcha_token?: string;
}

interface AuthContextValue {
  user: UserRead | null;
  token: string | null;
  loading: boolean;
  isDeviceToken: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<UserRead>;
  completeOidcLogin: (accessToken?: string, isDevice?: boolean) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const TOKEN_STORAGE_KEY = "initiative-token";
const DEVICE_TOKEN_KEY = "initiative-is-device-token";

const isNative = Capacitor.isNativePlatform();

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const { t } = useTranslation("auth");
  const [token, setTokenState] = useState<string | null>(null);
  const [isDeviceToken, setIsDeviceToken] = useState(false);
  const [user, setUserState] = useState<UserRead | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Keep the React user state and the api-client session flag in lockstep so
  // the 401 interceptor always knows whether to treat a 401 as session expiry
  // (non-null user) or as a not-logged-in visitor (null user).
  // Which answer about the account is the current one.
  //
  // Reading the account is not instant and several reads can be in the air at
  // once — two signals arriving together, a signal beside the catch-up a
  // reconnect does. Responses come back in whatever order the network gives
  // them, so the last to *arrive* is not the last to have been *asked for*.
  //
  // Two separate things decide whether a read may still be applied, and they
  // are separate because conflating them loses data either way:
  //
  // * `readSeqRef` / `appliedReadRef` — reads are numbered as they are made,
  //   and one applies only if no later-numbered read has already landed. That
  //   holds in both orders: a straggler never overwrites a newer answer, and a
  //   newer answer is never thrown away because an older one happened to land
  //   first.
  // * `identityEpochRef` — signing in or out replaces *who* the account is,
  //   which no read of the previous person may undo. Bumped there and nowhere
  //   else, so an ordinary read cannot invalidate another read.
  const readSeqRef = useRef(0);
  const appliedReadRef = useRef(0);
  const identityEpochRef = useRef(0);

  const setUser = useCallback((nextUser: UserRead | null) => {
    setUserState(nextUser);
    setHasActiveSession(nextUser !== null);
  }, []);

  /** Sign-in / sign-out: a new person, so every read in flight is stale. */
  const replaceIdentity = useCallback(
    (nextUser: UserRead | null) => {
      identityEpochRef.current += 1;
      setUser(nextUser);
    },
    [setUser]
  );

  // Load token on mount for native only (web uses HttpOnly cookie — no localStorage read needed)
  useEffect(() => {
    if (!isNative) return;
    try {
      const storedToken = getItem(TOKEN_STORAGE_KEY);
      const isDevice = getItem(DEVICE_TOKEN_KEY) === "true";
      if (storedToken) {
        setTokenState(storedToken);
        setIsDeviceToken(isDevice);
        setAuthToken(storedToken, isDevice);
      }
    } catch (err) {
      console.error("Failed to load token", err);
    }
  }, []);

  const refreshUser = useCallback(async () => {
    readSeqRef.current += 1;
    const readId = readSeqRef.current;
    const epoch = identityEpochRef.current;
    const response = await apiClient.get<UserRead>("/users/me");
    if (epoch !== identityEpochRef.current) {
      // Somebody signed in or out while this was in flight; it is about a
      // person who is no longer the one here.
      return;
    }
    if (readId <= appliedReadRef.current) {
      // A read made after this one has already landed, so this is the older
      // answer whichever order they arrived in.
      return;
    }
    appliedReadRef.current = readId;
    setUser(response.data);
  }, [setUser, replaceIdentity]);

  // Bootstrap user on mount — always attempt /users/me.
  // Web: cookie is sent automatically (withCredentials). Native: token was loaded by the effect above.
  useEffect(() => {
    const bootstrap = async () => {
      setLoading(true);
      try {
        const response = await apiClient.get<UserRead>("/users/me");
        setUser(response.data);
      } catch {
        replaceIdentity(null);
        if (isNative) {
          // Clear stale native token
          setTokenState(null);
          setIsDeviceToken(false);
          removeItem(TOKEN_STORAGE_KEY);
          removeItem(DEVICE_TOKEN_KEY);
          setAuthToken(null);
        }
      } finally {
        setLoading(false);
      }
    };
    void bootstrap();
  }, [setUser, replaceIdentity]);

  const login = async ({ email, password, deviceName }: LoginPayload) => {
    try {
      // On mobile, use device token endpoint
      if (isNative) {
        const name = deviceName || "Mobile Device";
        const response = await apiClient.post<{ device_token: string }>("/auth/device-token", {
          email,
          password,
          device_name: name,
        });
        const newToken = response.data.device_token;
        setAuthToken(newToken, true);
        setItem(TOKEN_STORAGE_KEY, newToken);
        setItem(DEVICE_TOKEN_KEY, "true");
        setTokenState(newToken);
        setIsDeviceToken(true);
        await refreshUser();
      } else {
        const params = new URLSearchParams();
        params.append("username", email);
        params.append("password", password);
        params.append("grant_type", "password");
        params.append("scope", "");
        params.append("client_id", "");
        params.append("client_secret", "");

        const response = await apiClient.post<{ access_token: string }>("/auth/token", params, {
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        });
        const newToken = response.data.access_token;
        // Keep token in memory for this session only — backend also set an HttpOnly cookie
        setAuthToken(newToken, false);
        removeItem(TOKEN_STORAGE_KEY);
        removeItem(DEVICE_TOKEN_KEY);
        setTokenState(newToken);
        setIsDeviceToken(false);
        await refreshUser();
      }
      markJustSignedIn();
    } catch (error) {
      throw new Error(getErrorMessage(error, "auth:login.defaultError"));
    }
  };

  const register = async ({
    email,
    password,
    username,
    full_name,
    inviteCode,
    timezone,
    captcha_token,
  }: RegisterPayload) => {
    const response = await apiClient.post<UserRead>(
      "/auth/register",
      { email, password, username, full_name, timezone, captcha_token },
      inviteCode
        ? {
            params: { invite_code: inviteCode },
          }
        : undefined
    );
    return response.data;
  };

  // Memoized: the OIDC callback page calls this from an effect, and this
  // function also sets the user it depends on. An unstable identity would make
  // that effect re-run on every render it causes — an endless /users/me loop.
  const completeOidcLogin = useCallback(
    async (accessToken?: string, isDevice = false) => {
      if (isDevice && accessToken) {
        // Native: store device token in persistent storage
        setAuthToken(accessToken, true);
        setItem(TOKEN_STORAGE_KEY, accessToken);
        setItem(DEVICE_TOKEN_KEY, "true");
        setTokenState(accessToken);
        setIsDeviceToken(true);
      }
      // Web: cookie was already set by the backend redirect — just fetch the user
      const me = await apiClient.get<UserRead>("/users/me");
      replaceIdentity(me.data);
      markJustSignedIn();
    },
    [setUser, replaceIdentity]
  );

  const logout = useCallback(async () => {
    // Fire the POST *first*, while the bearer token and cookie are still
    // in place — otherwise we may log out on the client without the
    // backend ever seeing the request, and the cached JWT/cookie can
    // keep authenticating subsequent requests until it expires naturally.
    //
    // Clear hasActiveSession before the POST so the interceptor ignores
    // any 401 that comes back from /auth/logout itself (can happen when
    // the cookie is already expired), preventing re-entry into this
    // same handler.
    setHasActiveSession(false);
    clearJustSignedIn();
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Ignore errors — proceed with local cleanup regardless.
    }
    replaceIdentity(null);
    setTokenState(null);
    setIsDeviceToken(false);
    setAuthToken(null);
    clearUploadToken();
    removeItem(TOKEN_STORAGE_KEY);
    removeItem(DEVICE_TOKEN_KEY);
    queryClient.clear();
  }, [setUser, replaceIdentity]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }
    const handleUnauthorized = () => {
      // The api-client session flag means this only fires for users who
      // were actually signed in, so it's safe to surface the toast here
      // without further checks.
      toast.error(t("session.expired"));
      void logout();
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [logout, t]);

  const value: AuthContextValue = {
    user,
    token,
    loading,
    isDeviceToken,
    login,
    register,
    completeOidcLogin,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
