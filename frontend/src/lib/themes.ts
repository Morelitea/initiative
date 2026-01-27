/**
 * Color theme definitions for the application.
 *
 * Each theme defines colors for both light and dark modes.
 * Colors are specified in OKLch format (without the oklch() wrapper)
 * as space-separated values: "lightness chroma hue"
 *
 * To add a new theme:
 * 1. Add an entry to the THEMES object with a unique id
 * 2. Define all color values for both light and dark modes
 * 3. The theme will automatically appear in the settings dropdown
 */

export interface ThemeColors {
  background: string;
  foreground: string;
  card: string;
  cardForeground: string;
  popover: string;
  popoverForeground: string;
  secondary: string;
  secondaryForeground: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  accentForeground: string;
  destructive: string;
  border: string;
  input: string;
  ring: string;
  chart1: string;
  chart2: string;
  chart3: string;
  chart4: string;
  chart5: string;
  sidebar: string;
  sidebarForeground: string;
  sidebarPrimary: string;
  sidebarPrimaryForeground: string;
  sidebarAccent: string;
  sidebarAccentForeground: string;
  sidebarBorder: string;
  sidebarRing: string;
}

export interface ThemeDefinition {
  id: string;
  name: string;
  description?: string;
  light: ThemeColors;
  dark: ThemeColors;
}

/**
 * Available color themes.
 * The "kobold" theme is the classic Initiative theme with deep indigo tones.
 */
export const THEMES: Record<string, ThemeDefinition> = {
  kobold: {
    id: "kobold",
    name: "Kobold",
    description: "The classic Initiative theme with deep indigo tones",
    light: {
      background: "1 0 0",
      foreground: "0.129 0.042 264.695",
      card: "1 0 0",
      cardForeground: "0.129 0.042 264.695",
      popover: "1 0 0",
      popoverForeground: "0.129 0.042 264.695",
      secondary: "0.968 0.007 247.896",
      secondaryForeground: "0.208 0.042 265.755",
      muted: "0.968 0.007 247.896",
      mutedForeground: "0.554 0.046 257.417",
      accent: "0.968 0.007 247.896",
      accentForeground: "0.208 0.042 265.755",
      destructive: "0.577 0.245 27.325",
      border: "0.929 0.013 255.508",
      input: "0.929 0.013 255.508",
      ring: "0.208 0.042 265.755",
      chart1: "0.646 0.222 41.116",
      chart2: "0.6 0.118 184.704",
      chart3: "0.398 0.07 227.392",
      chart4: "0.828 0.189 84.429",
      chart5: "0.769 0.188 70.08",
      sidebar: "0.984 0.003 247.858",
      sidebarForeground: "0.129 0.042 264.695",
      sidebarPrimary: "0.208 0.042 265.755",
      sidebarPrimaryForeground: "0.984 0.003 247.858",
      sidebarAccent: "0.968 0.007 247.896",
      sidebarAccentForeground: "0.208 0.042 265.755",
      sidebarBorder: "0.929 0.013 255.508",
      sidebarRing: "0.704 0.04 256.788",
    },
    dark: {
      background: "0.129 0.042 264.695",
      foreground: "0.984 0.003 247.858",
      card: "0.208 0.042 265.755",
      cardForeground: "0.984 0.003 247.858",
      popover: "0.208 0.042 265.755",
      popoverForeground: "0.984 0.003 247.858",
      secondary: "0.279 0.041 260.031",
      secondaryForeground: "0.984 0.003 247.858",
      muted: "0.279 0.041 260.031",
      mutedForeground: "0.704 0.04 256.788",
      accent: "0.279 0.041 260.031",
      accentForeground: "0.984 0.003 247.858",
      destructive: "0.704 0.191 22.216",
      border: "1 0 0 / 10%",
      input: "1 0 0 / 15%",
      ring: "0.929 0.013 255.508",
      chart1: "0.488 0.243 264.376",
      chart2: "0.696 0.17 162.48",
      chart3: "0.769 0.188 70.08",
      chart4: "0.627 0.265 303.9",
      chart5: "0.645 0.246 16.439",
      sidebar: "0.208 0.042 265.755",
      sidebarForeground: "0.984 0.003 247.858",
      sidebarPrimary: "0.488 0.243 264.376",
      sidebarPrimaryForeground: "0.984 0.003 247.858",
      sidebarAccent: "0.279 0.041 260.031",
      sidebarAccentForeground: "0.984 0.003 247.858",
      sidebarBorder: "1 0 0 / 10%",
      sidebarRing: "0.551 0.027 264.364",
    },
  },
};

export const DEFAULT_THEME = "kobold";

export const getThemeList = (): ThemeDefinition[] => Object.values(THEMES);

export const getTheme = (id: string): ThemeDefinition | undefined => THEMES[id];
