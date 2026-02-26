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
    description: "The classic Initiative theme with deep indigo tones.",
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
  displacer: {
    id: "displacer",
    name: "Displacer",
    description: "Catppuccin-inspired soothing pastel theme (Latte/Macchiato).",
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
      secondary: "0.378 0.043 275", // Surface1 #494d64
      secondaryForeground: "0.863 0.049 275", // Text #cad3f5
      muted: "0.378 0.043 275", // Surface1 #494d64
      mutedForeground: "0.730 0.043 273", // Subtext0 #a5adcb
      accent: "0.378 0.043 275", // Surface1 #494d64
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
  strahd: {
    id: "strahd",
    name: "Strahd",
    description: "Dark gothic theme with purple accents (Dracula/Alucard).",
    light: {
      // Alucard variant
      background: "0.99 0.02 95", // #fffbeb
      foreground: "0.22 0 0", // #1f1f1f
      card: "0.99 0.02 95", // #fffbeb
      cardForeground: "0.22 0 0", // #1f1f1f
      popover: "0.99 0.02 95", // #fffbeb
      popoverForeground: "0.22 0 0", // #1f1f1f
      secondary: "0.94 0.02 95", // slightly darker
      secondaryForeground: "0.22 0 0", // #1f1f1f
      muted: "0.94 0.02 95", // slightly darker
      mutedForeground: "0.52 0.04 260", // muted text
      accent: "0.94 0.02 95", // slightly darker
      accentForeground: "0.22 0 0", // #1f1f1f
      destructive: "0.52 0.19 25", // Red #cb3a2a
      border: "0.90 0.02 95", // border
      input: "0.90 0.02 95", // input
      ring: "0.48 0.19 290", // Purple #644ac9
      chart1: "0.48 0.13 50", // Orange #a34d14
      chart2: "0.47 0.10 230", // Cyan #036a96
      chart3: "0.48 0.19 290", // Purple #644ac9
      chart4: "0.52 0.11 85", // Yellow #846e15
      chart5: "0.44 0.14 140", // Green #14710a
      sidebar: "0.96 0.02 95", // slightly darker than background
      sidebarForeground: "0.22 0 0", // #1f1f1f
      sidebarPrimary: "0.48 0.19 290", // Purple #644ac9
      sidebarPrimaryForeground: "0.99 0.02 95", // light
      sidebarAccent: "0.94 0.02 95", // slightly darker
      sidebarAccentForeground: "0.22 0 0", // #1f1f1f
      sidebarBorder: "0.90 0.02 95", // border
      sidebarRing: "0.52 0.04 260", // muted
    },
    dark: {
      // Dracula
      background: "0.25 0.03 280", // Background #282a36
      foreground: "0.97 0.01 105", // Foreground #f8f8f2
      card: "0.36 0.03 275", // Current Line #44475a
      cardForeground: "0.97 0.01 105", // Foreground #f8f8f2
      popover: "0.36 0.03 275", // Current Line #44475a
      popoverForeground: "0.97 0.01 105", // Foreground #f8f8f2
      secondary: "0.42 0.03 275", // slightly lighter than current line
      secondaryForeground: "0.97 0.01 105", // Foreground #f8f8f2
      muted: "0.42 0.03 275", // slightly lighter than current line
      mutedForeground: "0.65 0.07 260", // Comment #6272a4 (lightened for contrast)
      accent: "0.42 0.03 275", // slightly lighter than current line
      accentForeground: "0.97 0.01 105", // Foreground #f8f8f2
      destructive: "0.68 0.24 25", // Red #ff5555
      border: "0.42 0.03 275", // border
      input: "0.42 0.03 275", // input
      ring: "0.72 0.15 300", // Purple #bd93f9
      chart1: "0.73 0.20 350", // Pink #ff79c6
      chart2: "0.88 0.11 205", // Cyan #8be9fd
      chart3: "0.72 0.15 300", // Purple #bd93f9
      chart4: "0.82 0.14 65", // Orange #ffb86c
      chart5: "0.88 0.25 145", // Green #50fa7b
      sidebar: "0.22 0.03 280", // slightly darker than background
      sidebarForeground: "0.97 0.01 105", // Foreground #f8f8f2
      sidebarPrimary: "0.72 0.15 300", // Purple #bd93f9
      sidebarPrimaryForeground: "0.25 0.03 280", // Background
      sidebarAccent: "0.36 0.03 275", // Current Line #44475a
      sidebarAccentForeground: "0.97 0.01 105", // Foreground #f8f8f2
      sidebarBorder: "0.42 0.03 275", // border
      sidebarRing: "0.65 0.07 260", // Comment #6272a4 (lightened)
    },
  },
  unicorn: {
    id: "unicorn",
    name: "Unicorn",
    description: "Full-spectrum neon rainbow — loud and proud.",
    light: {
      background: "1 0 0", // pure white
      foreground: "0.15 0.04 290", // near-black
      card: "1 0 0", // pure white
      cardForeground: "0.15 0.04 290", // near-black
      popover: "1 0 0", // pure white
      popoverForeground: "0.15 0.04 290", // near-black
      secondary: "0.97 0.005 0", // white
      secondaryForeground: "0.55 0.30 340", // hot pink
      muted: "0.97 0.005 0", // white
      mutedForeground: "0.45 0.18 180", // teal
      accent: "0.97 0.005 0", // white
      accentForeground: "0.55 0.28 25", // red
      destructive: "0.55 0.28 25", // red
      border: "0.55 0.30 340", // hot pink border
      input: "0.62 0.24 55", // orange input
      ring: "0.50 0.24 145", // green
      chart1: "0.55 0.30 15", // bold red
      chart2: "0.75 0.18 65", // warm orange
      chart3: "0.45 0.22 155", // deep green
      chart4: "0.65 0.12 230", // soft blue
      chart5: "0.40 0.28 310", // dark violet
      sidebar: "1 0 0", // pure white
      sidebarForeground: "0.15 0.04 290", // near-black
      sidebarPrimary: "0.50 0.30 300", // violet
      sidebarPrimaryForeground: "1 0 0", // pure white
      sidebarAccent: "0.97 0.005 0", // white
      sidebarAccentForeground: "0.50 0.24 145", // green
      sidebarBorder: "0.48 0.22 270", // indigo border
      sidebarRing: "0.62 0.24 55", // orange
    },
    dark: {
      background: "0.1353 0.0444 314.47", // dark purple-black
      foreground: "1 0 0", // pure white
      card: "0.18 0.05 300", // slightly lifted
      cardForeground: "1 0 0", // pure white
      popover: "0.18 0.05 300", // slightly lifted
      popoverForeground: "1 0 0", // pure white
      secondary: "0.16 0.04 300", // dark
      secondaryForeground: "0.85 0.30 145", // neon green
      muted: "0.16 0.04 300", // dark
      mutedForeground: "0.78 0.28 55", // neon orange
      accent: "0.16 0.04 300", // dark
      accentForeground: "0.72 0.30 340", // neon hot pink
      destructive: "0.65 0.30 25", // neon red
      border: "0.90 0.22 90", // neon yellow border
      input: "0.60 0.18 180", // neon teal input
      ring: "0.60 0.28 300", // neon violet
      chart1: "0.65 0.30 15", // neon red
      chart2: "0.82 0.16 65", // bright orange
      chart3: "0.55 0.24 155", // vivid green
      chart4: "0.78 0.10 230", // light blue
      chart5: "0.50 0.30 310", // deep violet
      sidebar: "0.12 0.04 300", // dark
      sidebarForeground: "1 0 0", // pure white
      sidebarPrimary: "0.78 0.28 55", // neon orange
      sidebarPrimaryForeground: "0.10 0.03 300", // near-black
      sidebarAccent: "0.16 0.04 300", // dark
      sidebarAccentForeground: "0.72 0.30 340", // neon hot pink
      sidebarBorder: "0.85 0.30 145", // neon green border
      sidebarRing: "0.65 0.30 25", // neon red
  darkKnight: {
    id: "darkKnight",
    name: "Dark Knight",
    description: "AMOLED black theme with dark red and yellow accents.",
    light: {
      background: "0.78 0 0", // medium grey
      foreground: "0.12 0 0", // near-black
      card: "0.82 0 0", // slightly lighter surface
      cardForeground: "0.12 0 0",
      popover: "0.82 0 0",
      popoverForeground: "0.12 0 0",
      secondary: "0.72 0 0", // slightly darker surface
      secondaryForeground: "0.12 0 0",
      muted: "0.72 0 0",
      mutedForeground: "0.38 0 0", // dark grey muted text
      accent: "0.70 0 0",
      accentForeground: "0.12 0 0",
      destructive: "0.55 0.24 27",
      border: "0.64 0 0",
      input: "0.72 0 0",
      ring: "0.30 0.15 10", // dark maroon focus ring
      chart1: "0.36 0.17 10", // dark maroon
      chart2: "0.72 0.16 85", // golden yellow
      chart3: "0.58 0.19 45", // dark orange
      chart4: "0.25 0.12 8", // deep burgundy
      chart5: "0.62 0.14 70", // amber
      sidebar: "0.74 0 0", // slightly darker than background
      sidebarForeground: "0.12 0 0",
      sidebarPrimary: "0.30 0.15 10", // dark maroon
      sidebarPrimaryForeground: "0.95 0 0",
      sidebarAccent: "0.70 0 0",
      sidebarAccentForeground: "0.12 0 0",
      sidebarBorder: "0.64 0 0",
      sidebarRing: "0.52 0.10 40",
    },
    dark: {
      background: "0 0 0", // true black — AMOLED
      foreground: "0.98 0 0", // near-white
      card: "0.1 0 0", // very dark grey
      cardForeground: "0.98 0 0",
      popover: "0.1 0 0",
      popoverForeground: "0.98 0 0",
      secondary: "0.14 0 0", // slightly elevated surface
      secondaryForeground: "0.98 0 0",
      muted: "0.14 0 0",
      mutedForeground: "0.55 0 0",
      accent: "0.18 0 0",
      accentForeground: "0.98 0 0",
      destructive: "0.68 0.24 25",
      border: "0.18 0 0",
      input: "0.14 0 0",
      ring: "0.85 0.18 90", // bat-signal yellow focus ring
      chart1: "0.40 0.18 10", // dark maroon
      chart2: "0.85 0.18 90", // bat-signal yellow
      chart3: "0.70 0.20 45", // dark orange
      chart4: "0.30 0.14 8", // deep burgundy
      chart5: "0.78 0.15 75", // amber gold
      sidebar: "0 0 0", // true black sidebar
      sidebarForeground: "0.98 0 0",
      sidebarPrimary: "0.85 0.18 90", // bat-signal yellow
      sidebarPrimaryForeground: "0.08 0 0",
      sidebarAccent: "0.14 0 0",
      sidebarAccentForeground: "0.98 0 0",
      sidebarBorder: "0.18 0 0",
      sidebarRing: "0.55 0.12 40",
    },
  },
  orc: {
    id: "orc",
    name: "ORC",
    description: "Earthy green theme with vivid orc-skin green accents. ORC ORC ORC!",
    light: {
      background: "0.93 0.02 115", // light earthy field
      foreground: "0.18 0.05 135", // dark forest green text
      card: "0.96 0.01 110", // off-white card
      cardForeground: "0.18 0.05 135",
      popover: "0.96 0.01 110",
      popoverForeground: "0.18 0.05 135",
      secondary: "0.86 0.03 120", // mossy surface
      secondaryForeground: "0.18 0.05 135",
      muted: "0.86 0.03 120",
      mutedForeground: "0.45 0.05 135", // medium forest muted
      accent: "0.84 0.04 120",
      accentForeground: "0.18 0.05 135",
      destructive: "0.55 0.24 27",
      border: "0.80 0.04 125",
      input: "0.86 0.03 120",
      ring: "0.42 0.20 140", // forest green focus ring
      chart1: "0.42 0.20 140", // forest green
      chart2: "0.60 0.18 115", // yellow-green
      chart3: "0.52 0.16 160", // teal-green
      chart4: "0.55 0.15 80", // olive
      chart5: "0.48 0.14 50", // earthy brown
      sidebar: "0.88 0.03 120", // mossy sidebar
      sidebarForeground: "0.18 0.05 135",
      sidebarPrimary: "0.42 0.20 140", // forest green
      sidebarPrimaryForeground: "0.96 0.01 110",
      sidebarAccent: "0.84 0.04 120",
      sidebarAccentForeground: "0.18 0.05 135",
      sidebarBorder: "0.80 0.04 125",
      sidebarRing: "0.52 0.08 135",
    },
    dark: {
      background: "0.12 0.03 140", // dark cave/swamp
      foreground: "0.90 0.05 105", // warm bone-ivory text
      card: "0.17 0.04 135", // slightly lighter surface
      cardForeground: "0.90 0.05 105",
      popover: "0.17 0.04 135",
      popoverForeground: "0.90 0.05 105",
      secondary: "0.22 0.04 135", // elevated surface
      secondaryForeground: "0.90 0.05 105",
      muted: "0.22 0.04 135",
      mutedForeground: "0.60 0.05 130", // muted green-grey
      accent: "0.26 0.05 135",
      accentForeground: "0.90 0.05 105",
      destructive: "0.68 0.24 25",
      border: "0.26 0.05 135",
      input: "0.22 0.04 135",
      ring: "0.72 0.25 140", // vivid orc-skin green
      chart1: "0.75 0.20 140", // vivid sage/orc green
      chart2: "0.80 0.18 75", // bright amber/honey
      chart3: "0.68 0.22 30", // warm rust/terracotta
      chart4: "0.72 0.16 170", // warm sage teal
      chart5: "0.85 0.15 95", // bright warm yellow
      sidebar: "0.10 0.025 140", // darker cave sidebar
      sidebarForeground: "0.90 0.05 105",
      sidebarPrimary: "0.72 0.25 140", // vivid orc green
      sidebarPrimaryForeground: "0.08 0 0",
      sidebarAccent: "0.22 0.04 135",
      sidebarAccentForeground: "0.90 0.05 105",
      sidebarBorder: "0.26 0.05 135",
      sidebarRing: "0.45 0.10 140",
    },
  },
  aboleth: {
    id: "aboleth",
    name: "Aboleth",
    description: "Monokai-inspired dark lair with vivid bioluminescent accent colors.",
    light: {
      background: "0.97 0.01 95", // warm parchment
      foreground: "0.20 0.02 95", // dark olive text
      card: "0.99 0 0", // near-white card
      cardForeground: "0.20 0.02 95",
      popover: "0.99 0 0",
      popoverForeground: "0.20 0.02 95",
      secondary: "0.91 0.01 95", // slightly tinted surface
      secondaryForeground: "0.20 0.02 95",
      muted: "0.91 0.01 95",
      mutedForeground: "0.52 0.03 95", // olive-grey muted text
      accent: "0.88 0.01 95",
      accentForeground: "0.20 0.02 95",
      destructive: "0.52 0.28 355", // hot pink-red (Monokai red, darkened)
      border: "0.84 0.02 95",
      input: "0.91 0.01 95",
      ring: "0.52 0.18 290", // deep purple focus ring
      chart1: "0.52 0.15 200", // deep cyan
      chart2: "0.52 0.18 290", // deep purple
      chart3: "0.62 0.18 50", // amber orange
      chart4: "0.58 0.28 355", // deep hot pink
      chart5: "0.50 0.22 130", // Monokai lime green #A6E22E
      sidebar: "0.93 0.01 95", // slightly darker parchment
      sidebarForeground: "0.20 0.02 95",
      sidebarPrimary: "0.52 0.18 290", // deep purple
      sidebarPrimaryForeground: "0.97 0.01 95",
      sidebarAccent: "0.88 0.01 95",
      sidebarAccentForeground: "0.20 0.02 95",
      sidebarBorder: "0.84 0.02 95",
      sidebarRing: "0.58 0.08 95",
    },
    dark: {
      background: "0.17 0.01 105", // Monokai bg #272822
      foreground: "0.97 0.01 105", // Monokai fg #F8F8F2
      card: "0.22 0.01 100", // slightly elevated surface
      cardForeground: "0.97 0.01 105",
      popover: "0.22 0.01 100",
      popoverForeground: "0.97 0.01 105",
      secondary: "0.27 0.01 95", // Monokai selection #3E3D32
      secondaryForeground: "0.97 0.01 105",
      muted: "0.27 0.01 95",
      mutedForeground: "0.50 0.03 95", // Monokai comment #75715E
      accent: "0.30 0.01 95",
      accentForeground: "0.97 0.01 105",
      destructive: "0.62 0.28 355", // Monokai red #F92672
      border: "0.30 0.02 95",
      input: "0.27 0.01 95",
      ring: "0.70 0.18 290", // Monokai purple #AE81FF
      chart1: "0.85 0.10 200", // Monokai cyan #66D9E8
      chart2: "0.70 0.18 290", // Monokai purple #AE81FF
      chart3: "0.75 0.18 55", // Monokai orange #FD971F
      chart4: "0.62 0.28 355", // Monokai hot pink #F92672
      chart5: "0.82 0.22 130", // Monokai lime green #A6E22E
      sidebar: "0.14 0.01 105", // darker lair — deeper cave
      sidebarForeground: "0.97 0.01 105",
      sidebarPrimary: "0.85 0.10 200", // Monokai cyan
      sidebarPrimaryForeground: "0.10 0.01 105",
      sidebarAccent: "0.22 0.01 100",
      sidebarAccentForeground: "0.97 0.01 105",
      sidebarBorder: "0.30 0.02 95",
      sidebarRing: "0.50 0.08 95",
    },
  },
};

export const DEFAULT_THEME = "kobold";

export const getThemeList = (): ThemeDefinition[] => Object.values(THEMES);

export const getTheme = (id: string): ThemeDefinition | undefined => THEMES[id];
