import { createContext, useCallback, useContext, useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const THEME_STORAGE_KEY = 'initiative-theme';

const getPreferredTheme = (): Theme => {
  if (typeof window === 'undefined') {
    return 'light';
  }
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') {
    return stored;
  }
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
};

const applyThemeClass = (theme: Theme) => {
  if (typeof document === 'undefined') {
    return;
  }
  if (theme === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
};

export const ThemeProvider = ({ children }: { children: React.ReactNode }) => {
  const [theme, setThemeState] = useState<Theme>(() => getPreferredTheme());

  useEffect(() => {
    applyThemeClass(theme);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return;
    }
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const handler = (event: MediaQueryListEvent) => {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (stored === 'light' || stored === 'dark') {
        return;
      }
      setThemeState(event.matches ? 'dark' : 'light');
    };

    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const setTheme = useCallback((nextTheme: Theme) => {
    setThemeState(nextTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === 'dark' ? 'light' : 'dark'));
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>{children}</ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
