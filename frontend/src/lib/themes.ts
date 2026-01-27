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
  catppuccin: {
    id: "catppuccin",
    name: "Catppuccin",
    description: "Soothing pastel theme (Latte/Macchiato)",
    light: {
      // Latte flavor
      background: "0.959 0.009 255", // Base #eff1f5
      foreground: "0.413 0.043 277", // Text #4c4f69
      card: "0.959 0.009 255", // Base #eff1f5
      cardForeground: "0.413 0.043 277", // Text #4c4f69
      popover: "0.959 0.009 255", // Base #eff1f5
      popoverForeground: "0.413 0.043 277", // Text #4c4f69
      secondary: "0.862 0.016 264", // Surface0 #ccd0da
      secondaryForeground: "0.413 0.043 277", // Text #4c4f69
      muted: "0.862 0.016 264", // Surface0 #ccd0da
      mutedForeground: "0.524 0.035 274", // Subtext0 #6c6f85
      accent: "0.862 0.016 264", // Surface0 #ccd0da
      accentForeground: "0.413 0.043 277", // Text #4c4f69
      destructive: "0.528 0.239 17", // Red #d20f39
      border: "0.806 0.019 265", // Surface1 #bcc0cc
      input: "0.806 0.019 265", // Surface1 #bcc0cc
      ring: "0.621 0.184 271", // Lavender #7287fd
      chart1: "0.661 0.224 42", // Peach #fe640b
      chart2: "0.575 0.111 195", // Teal #179299
      chart3: "0.498 0.261 303", // Mauve #8839ef
      chart4: "0.700 0.170 70", // Yellow #df8e1d
      chart5: "0.595 0.180 142", // Green #40a02b
      sidebar: "0.934 0.011 262", // Mantle #e6e9ef
      sidebarForeground: "0.413 0.043 277", // Text #4c4f69
      sidebarPrimary: "0.498 0.261 303", // Mauve #8839ef
      sidebarPrimaryForeground: "0.959 0.009 255", // Base #eff1f5
      sidebarAccent: "0.862 0.016 264", // Surface0 #ccd0da
      sidebarAccentForeground: "0.413 0.043 277", // Text #4c4f69
      sidebarBorder: "0.806 0.019 265", // Surface1 #bcc0cc
      sidebarRing: "0.635 0.028 272", // Overlay0 #9ca0b0
    },
    dark: {
      // Macchiato flavor
      background: "0.224 0.036 277", // Base #24273a
      foreground: "0.863 0.049 275", // Text #cad3f5
      card: "0.298 0.040 275", // Surface0 #363a4f
      cardForeground: "0.863 0.049 275", // Text #cad3f5
      popover: "0.298 0.040 275", // Surface0 #363a4f
      popoverForeground: "0.863 0.049 275", // Text #cad3f5
      secondary: "0.298 0.040 275", // Surface0 #363a4f
      secondaryForeground: "0.863 0.049 275", // Text #cad3f5
      muted: "0.298 0.040 275", // Surface0 #363a4f
      mutedForeground: "0.730 0.043 273", // Subtext0 #a5adcb
      accent: "0.298 0.040 275", // Surface0 #363a4f
      accentForeground: "0.863 0.049 275", // Text #cad3f5
      destructive: "0.721 0.135 15", // Red #ed8796
      border: "0.378 0.043 275", // Surface1 #494d64
      input: "0.378 0.043 275", // Surface1 #494d64
      ring: "0.798 0.080 275", // Lavender #b7bdf8
      chart1: "0.787 0.120 48", // Peach #f5a97f
      chart2: "0.820 0.075 175", // Teal #8bd5ca
      chart3: "0.755 0.130 303", // Mauve #c6a0f6
      chart4: "0.877 0.085 85", // Yellow #eed49f
      chart5: "0.832 0.105 135", // Green #a6da95
      sidebar: "0.192 0.033 277", // Mantle #1e2030
      sidebarForeground: "0.863 0.049 275", // Text #cad3f5
      sidebarPrimary: "0.755 0.130 303", // Mauve #c6a0f6
      sidebarPrimaryForeground: "0.166 0.027 277", // Crust #181926
      sidebarAccent: "0.298 0.040 275", // Surface0 #363a4f
      sidebarAccentForeground: "0.863 0.049 275", // Text #cad3f5
      sidebarBorder: "0.378 0.043 275", // Surface1 #494d64
      sidebarRing: "0.530 0.044 275", // Overlay0 #6e738d
    },
  },
};

export const DEFAULT_THEME = "kobold";

export const getThemeList = (): ThemeDefinition[] => Object.values(THEMES);

export const getTheme = (id: string): ThemeDefinition | undefined => THEMES[id];
