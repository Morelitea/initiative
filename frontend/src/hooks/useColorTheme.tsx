import { useEffect } from "react";

import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { THEMES, DEFAULT_THEME, getTheme, type ThemeColors } from "@/lib/themes";

/**
 * Maps ThemeColors properties to CSS variable names.
 */
const CSS_VAR_MAP: Record<keyof ThemeColors, string> = {
  background: "--background",
  foreground: "--foreground",
  card: "--card",
  cardForeground: "--card-foreground",
  popover: "--popover",
  popoverForeground: "--popover-foreground",
  secondary: "--secondary",
  secondaryForeground: "--secondary-foreground",
  muted: "--muted",
  mutedForeground: "--muted-foreground",
  accent: "--accent",
  accentForeground: "--accent-foreground",
  destructive: "--destructive",
  border: "--border",
  input: "--input",
  ring: "--ring",
  chart1: "--chart-1",
  chart2: "--chart-2",
  chart3: "--chart-3",
  chart4: "--chart-4",
  chart5: "--chart-5",
  sidebar: "--sidebar",
  sidebarForeground: "--sidebar-foreground",
  sidebarPrimary: "--sidebar-primary",
  sidebarPrimaryForeground: "--sidebar-primary-foreground",
  sidebarAccent: "--sidebar-accent",
  sidebarAccentForeground: "--sidebar-accent-foreground",
  sidebarBorder: "--sidebar-border",
  sidebarRing: "--sidebar-ring",
};

/**
 * Applies theme colors to CSS custom properties.
 *
 * This hook reads the user's color_theme preference and the current
 * light/dark mode, then applies the appropriate color values to CSS
 * custom properties on the document root.
 *
 * The hook automatically re-applies colors when:
 * - The user's color_theme preference changes
 * - The light/dark mode is toggled
 */
export const useColorTheme = () => {
  const { user } = useAuth();
  const { resolvedTheme } = useTheme();

  const colorThemeId = user?.color_theme ?? DEFAULT_THEME;

  useEffect(() => {
    const theme = getTheme(colorThemeId) ?? THEMES[DEFAULT_THEME];
    const colors = resolvedTheme === "dark" ? theme.dark : theme.light;

    const root = document.documentElement;

    // Apply each color to its CSS variable
    for (const [key, cssVar] of Object.entries(CSS_VAR_MAP)) {
      const colorValue = colors[key as keyof ThemeColors];
      // Handle values with alpha (e.g., "1 0 0 / 10%")
      if (colorValue.includes("/")) {
        root.style.setProperty(cssVar, `oklch(${colorValue})`);
      } else {
        root.style.setProperty(cssVar, `oklch(${colorValue})`);
      }
    }
  }, [colorThemeId, resolvedTheme]);
};
