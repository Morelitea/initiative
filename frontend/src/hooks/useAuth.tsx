import { ReactNode, createContext, useContext, useEffect, useState, useCallback } from "react";
import type { AxiosError } from "axios";
import { Capacitor } from "@capacitor/core";

import { apiClient, setAuthToken, AUTH_UNAUTHORIZED_EVENT } from "@/api/client";
import { getStoredToken, setStoredToken, clearStoredToken } from "@/lib/serverStorage";
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

  // Load token on mount
  useEffect(() => {
    const loadToken = async () => {
      try {
        if (isNative) {
          // On mobile, use Preferences storage
          const storedToken = await getStoredToken();
          if (storedToken) {
            setTokenState(storedToken);
            setIsDeviceToken(true); // Mobile always uses device tokens
            setAuthToken(storedToken, true);
          }
        } else {
          // On web, use localStorage
          const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
          const isDevice = localStorage.getItem(DEVICE_TOKEN_KEY) === "true";
          if (storedToken) {
            setTokenState(storedToken);
            setIsDeviceToken(isDevice);
            setAuthToken(storedToken, isDevice);
          }
        }
      } catch (err) {
        console.error("Failed to load token", err);
      }
    };
    void loadToken();
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
        if (isNative) {
          await clearStoredToken();
        } else {
          localStorage.removeItem(TOKEN_STORAGE_KEY);
          localStorage.removeItem(DEVICE_TOKEN_KEY);
        }
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
        // Set auth token BEFORE React state to avoid race with bootstrap effect
        setAuthToken(newToken, true);
        await setStoredToken(newToken);
        setTokenState(newToken);
        setIsDeviceToken(true);
        await refreshUser();
      } else {
        // On web, use regular JWT login
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
        // Set auth token BEFORE React state to avoid race with bootstrap effect
        setAuthToken(newToken, false);
        localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
        localStorage.removeItem(DEVICE_TOKEN_KEY);
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
    setTokenState(accessToken);
    setIsDeviceToken(isDevice);
    if (isDevice) {
      await setStoredToken(accessToken); // Capacitor Preferences (persistent)
      localStorage.setItem(DEVICE_TOKEN_KEY, "true");
    } else {
      localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
      localStorage.removeItem(DEVICE_TOKEN_KEY);
    }
    setAuthToken(accessToken, isDevice);
    const me = await apiClient.get<User>("/users/me");
    setUser(me.data);
  };

  const logout = useCallback(async () => {
    setTokenState(null);
    setIsDeviceToken(false);
    setUser(null);
    setAuthToken(null);
    if (isNative) {
      await clearStoredToken();
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(DEVICE_TOKEN_KEY);
    }
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
