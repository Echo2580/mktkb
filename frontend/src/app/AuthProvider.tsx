import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, isApiError, setCsrfToken, onUnauthorized, errorMessage } from '../api/client';
import type { User } from '../api/client';

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  bootError: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const mounted = useRef(true);

  const clear = useCallback(() => {
    setCsrfToken(null);
    setUser(null);
    setStatus('anonymous');
  }, []);

  const refresh = useCallback(async () => {
    try {
      const session = await api.me();
      if (!mounted.current) return;
      setCsrfToken(session.csrf_token);
      setUser(session.user);
      setStatus('authenticated');
      setBootError(null);
    } catch (error) {
      if (!mounted.current) return;
      clear();
      if (isApiError(error) && error.status === 401) {
        setBootError(null);
      } else {
        setBootError(errorMessage(error));
      }
    }
  }, [clear]);

  useEffect(() => {
    mounted.current = true;
    onUnauthorized(() => {
      if (!mounted.current) return;
      clear();
      setBootError('登录状态已失效，请重新登录');
    });
    void refresh();
    return () => {
      mounted.current = false;
      onUnauthorized(null);
    };
  }, [clear, refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const session = await api.login(username, password);
    setCsrfToken(session.csrf_token);
    setUser(session.user);
    setStatus('authenticated');
    setBootError(null);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (error) {
      // 服务端会话可能仍有效；不静默丢弃本地状态，交由调用方提示。
      if (isApiError(error) && error.status === 401) {
        clear();
        return;
      }
      throw error;
    }
    clear();
  }, [clear]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, bootError, login, logout, refresh }),
    [status, user, bootError, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth 必须在 AuthProvider 内使用');
  return value;
}
