import { useEffect } from "react";

import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { DEFAULT_THEME, getTheme, THEMES, type ThemeColors } from "@/lib/themes";

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
 * A color theme's tokens as CSS custom properties (`--background` →
 * `oklch(…)`), for one resolved mode. What {@link useColorTheme} applies to
 * this document, and what an embedded app is handed so it can wear the same
 * palette (see `GuildAppPage`).
 */
export const themeCssVariables = (
  colorThemeId: string,
  resolvedTheme: "light" | "dark"
): Record<string, string> => {
  const theme = getTheme(colorThemeId) ?? THEMES[DEFAULT_THEME];
  const colors = resolvedTheme === "dark" ? theme.dark : theme.light;
  const variables: Record<string, string> = {};
  for (const [key, cssVar] of Object.entries(CSS_VAR_MAP)) {
    variables[cssVar] = `oklch(${colors[key as keyof ThemeColors]})`;
  }
  return variables;
};

/**
 * The palette as an embedded app should wear it: the color theme's tokens
 * plus `--primary` / `--primary-foreground` / `--ring`, which this document
 * derives from the guild accent through the `--accent-<mode>-*` indirection.
 * An iframe on another origin cannot read this document's custom properties,
 * so the indirection is resolved here and the result travels as plain colors.
 */
export const effectiveThemeColors = (
  colorThemeId: string,
  resolvedTheme: "light" | "dark"
): Record<string, string> => {
  const variables = themeCssVariables(colorThemeId, resolvedTheme);
  if (typeof document === "undefined") return variables;

  const styles = getComputedStyle(document.documentElement);
  const accentTriplet = (name: string): string | null => {
    const value = styles.getPropertyValue(name).trim();
    // The accent vars hold bare oklch triplets ("L C H"); anything else means
    // the var is unset (or an environment, like jsdom, that can't resolve it).
    return /^[\d.]+\s+[\d.]+\s+[\d.]+$/.test(value) ? value : null;
  };

  const accent = accentTriplet(`--accent-${resolvedTheme}-color`);
  const accentForeground = accentTriplet(`--accent-${resolvedTheme}-foreground`);
  if (accent) {
    variables["--primary"] = `oklch(${accent})`;
    variables["--ring"] = `oklch(${accent})`;
  }
  if (accentForeground) {
    variables["--primary-foreground"] = `oklch(${accentForeground})`;
  }
  return variables;
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
    const root = document.documentElement;
    for (const [cssVar, value] of Object.entries(themeCssVariables(colorThemeId, resolvedTheme))) {
      root.style.setProperty(cssVar, value);
    }
  }, [colorThemeId, resolvedTheme]);
};
