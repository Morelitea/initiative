/**
 * Tone → theme color.
 *
 * The single reason a widget names a `Tone` instead of a color: every value
 * here resolves to a theme token, so a widget cannot paint itself invisible on
 * a dark background, cannot imitate app chrome, and cannot smuggle a `url()`
 * into a style. It also means a themed install restyles widget output for free,
 * including widgets we have never seen.
 */

import { SERIES_TONES, type Tone } from "./sceneSpec";

const TONE_COLORS: Record<Tone, string> = {
  accent: "var(--primary)",
  positive: "var(--color-green-500)",
  negative: "var(--destructive)",
  warning: "var(--color-yellow-500)",
  neutral: "var(--foreground)",
  muted: "var(--muted-foreground)",
  "series-1": "var(--chart-1)",
  "series-2": "var(--chart-2)",
  "series-3": "var(--chart-3)",
  "series-4": "var(--chart-4)",
  "series-5": "var(--chart-5)",
};

/** Falls back to the accent rather than to nothing: an unknown tone can't reach
 *  here (the validator rejects it), so this only covers our own omissions. */
export const toneColor = (tone: Tone | undefined): string =>
  tone ? (TONE_COLORS[tone] ?? TONE_COLORS.accent) : TONE_COLORS.accent;

/** The color for the nth series when the scene didn't choose one. Wraps, so a
 *  scene with more series than palette entries still renders. */
export const seriesColor = (index: number, tone?: Tone): string =>
  tone ? toneColor(tone) : toneColor(SERIES_TONES[index % SERIES_TONES.length]);

/** Text tones map to classes so they inherit the theme's foreground handling
 *  rather than being painted a literal color. The three semantic tones are the
 *  same pairs the stats cards use, so a "good" number reads the same green
 *  wherever the app shows one. */
const TONE_TEXT_CLASSES: Record<Tone, string> = {
  accent: "text-primary",
  positive: "text-green-600 dark:text-green-400",
  negative: "text-red-600 dark:text-red-400",
  warning: "text-yellow-600 dark:text-yellow-400",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
  "series-1": "text-foreground",
  "series-2": "text-foreground",
  "series-3": "text-foreground",
  "series-4": "text-foreground",
  "series-5": "text-foreground",
};

export const toneTextClass = (tone: Tone | undefined): string =>
  tone ? (TONE_TEXT_CLASSES[tone] ?? "text-foreground") : "text-foreground";
