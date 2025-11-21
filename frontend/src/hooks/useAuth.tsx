import { ReactNode, createContext, useContext, useEffect, useState } from 'react';

import { apiClient, setAuthToken } from '../api/client';
import { User } from '../types/api';

interface LoginPayload {
  email: string;
  password: string;
}

interface RegisterPayload extends LoginPayload {
  full_name?: string;
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<User>;
  completeOidcLogin: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const TOKEN_STORAGE_KEY = 'pour-priority-token';

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_STORAGE_KEY));
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    setLoading(true);
    setAuthToken(token);
    const bootstrap = async () => {
      if (!token) {
        setUser(null);
        setLoading(false);
        return;
      }
      try {
        const response = await apiClient.get<User>('/users/me');
        setUser(response.data);
      } catch (error) {
        console.error('Failed to restore session', error);
        setToken(null);
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      } finally {
        setLoading(false);
      }
    };
    void bootstrap();
  }, [token]);

  const login = async ({ email, password }: LoginPayload) => {
    const params = new URLSearchParams();
    params.append('username', email);
    params.append('password', password);
    params.append('grant_type', 'password');
    params.append('scope', '');
    params.append('client_id', '');
    params.append('client_secret', '');

    const response = await apiClient.post<{ access_token: string }>('/auth/token', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    const newToken = response.data.access_token;
    setToken(newToken);
    localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
    setAuthToken(newToken);

    const me = await apiClient.get<User>('/users/me');
    setUser(me.data);
  };

  const register = async ({ email, password, full_name }: RegisterPayload) => {
    const response = await apiClient.post<User>('/auth/register', { email, password, full_name });
    return response.data;
  };

  const completeOidcLogin = async (accessToken: string) => {
    setToken(accessToken);
    localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
    setAuthToken(accessToken);
    const me = await apiClient.get<User>('/users/me');
    setUser(me.data);
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setAuthToken(null);
  };

  const value: AuthContextValue = {
    user,
    token,
    loading,
    login,
    register,
    completeOidcLogin,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
