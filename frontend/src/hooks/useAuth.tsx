import { ReactNode, createContext, useContext, useEffect, useState, useCallback } from "react";
import type { AxiosError } from "axios";
import { Capacitor } from "@capacitor/core";

import { apiClient, setAuthToken, AUTH_UNAUTHORIZED_EVENT } from "@/api/client";
import { getItem, setItem, removeItem } from "@/lib/storage";
import { User } from "../types/api";

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
  user: User | null;
  token: string | null;
  loading: boolean;
  isDeviceToken: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<User>;
  completeOidcLogin: (token: string, isDevice?: boolean) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const TOKEN_STORAGE_KEY = "initiative-token";
const DEVICE_TOKEN_KEY = "initiative-is-device-token";

const isNative = Capacitor.isNativePlatform();

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [token, setTokenState] = useState<string | null>(null);
  const [isDeviceToken, setIsDeviceToken] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // Load token on mount (storage is pre-hydrated by initStorage)
  useEffect(() => {
    try {
      const storedToken = getItem(TOKEN_STORAGE_KEY);
      const isDevice = isNative || getItem(DEVICE_TOKEN_KEY) === "true";
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
    if (!token) {
      setUser(null);
      return;
    }
    const response = await apiClient.get<User>("/users/me");
    setUser(response.data);
  }, [token]);

  // Bootstrap user after token is loaded
  useEffect(() => {
    const bootstrap = async () => {
      if (!token) {
        setUser(null);
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        await refreshUser();
      } catch (error) {
        console.error("Failed to restore session", error);
        // Clear invalid token
        setTokenState(null);
        setIsDeviceToken(false);
        removeItem(TOKEN_STORAGE_KEY);
        removeItem(DEVICE_TOKEN_KEY);
        setUser(null);
        setAuthToken(null);
      } finally {
        setLoading(false);
      }
    };
    void bootstrap();
  }, [token, refreshUser]);

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
        setAuthToken(newToken, false);
        setItem(TOKEN_STORAGE_KEY, newToken);
        removeItem(DEVICE_TOKEN_KEY);
        setTokenState(newToken);
        setIsDeviceToken(false);
        await refreshUser();
      }
    } catch (error) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      throw new Error(detail ?? "Unable to log in. Check your credentials.");
    }
  };

  const register = async ({ email, password, full_name, inviteCode }: RegisterPayload) => {
    const response = await apiClient.post<User>(
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

  const completeOidcLogin = async (accessToken: string, isDevice = false) => {
    setAuthToken(accessToken, isDevice);
    setItem(TOKEN_STORAGE_KEY, accessToken);
    if (isDevice) {
      setItem(DEVICE_TOKEN_KEY, "true");
    } else {
      removeItem(DEVICE_TOKEN_KEY);
    }
    setTokenState(accessToken);
    setIsDeviceToken(isDevice);
    const me = await apiClient.get<User>("/users/me");
    setUser(me.data);
  };

  const logout = useCallback(async () => {
    setTokenState(null);
    setIsDeviceToken(false);
    setUser(null);
    setAuthToken(null);
    removeItem(TOKEN_STORAGE_KEY);
    removeItem(DEVICE_TOKEN_KEY);
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
