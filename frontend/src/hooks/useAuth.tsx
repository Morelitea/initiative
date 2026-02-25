import { ReactNode, createContext, useContext, useEffect, useState, useCallback } from "react";
import { Capacitor } from "@capacitor/core";

import { apiClient, setAuthToken, AUTH_UNAUTHORIZED_EVENT } from "@/api/client";
import { getItem, setItem, removeItem } from "@/lib/storage";
import { getErrorMessage } from "@/lib/errorMessage";
import { queryClient } from "@/lib/queryClient";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

interface LoginPayload {
  email: string;
  password: string;
  deviceName?: string; // For mobile device token login
}

interface RegisterPayload {
  email: string;
  password: string;
  full_name?: string;
  inviteCode?: string;
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
  const [token, setTokenState] = useState<string | null>(null);
  const [isDeviceToken, setIsDeviceToken] = useState(false);
  const [user, setUser] = useState<UserRead | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

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
    const response = await apiClient.get<UserRead>("/users/me");
    setUser(response.data);
  }, []);

  // Bootstrap user on mount — always attempt /users/me.
  // Web: cookie is sent automatically (withCredentials). Native: token was loaded by the effect above.
  useEffect(() => {
    const bootstrap = async () => {
      setLoading(true);
      try {
        const response = await apiClient.get<UserRead>("/users/me");
        setUser(response.data);
      } catch {
        setUser(null);
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
  }, []);

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
    } catch (error) {
      throw new Error(getErrorMessage(error, "auth:login.defaultError"));
    }
  };

  const register = async ({ email, password, full_name, inviteCode }: RegisterPayload) => {
    const response = await apiClient.post<UserRead>(
      "/auth/register",
      { email, password, full_name },
      inviteCode
        ? {
            params: { invite_code: inviteCode },
          }
        : undefined
    );
    return response.data;
  };

  const completeOidcLogin = async (accessToken?: string, isDevice = false) => {
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
    setUser(me.data);
  };

  const logout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Ignore errors — proceed with local cleanup regardless
    }
    setTokenState(null);
    setIsDeviceToken(false);
    setUser(null);
    setAuthToken(null);
    removeItem(TOKEN_STORAGE_KEY);
    removeItem(DEVICE_TOKEN_KEY);
    queryClient.clear();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }
    const handleUnauthorized = () => {
      void logout();
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [logout]);

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
