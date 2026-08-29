/**
 * Picking text that can be read on a colour someone chose.
 *
 * A guild picks its banner's fill, so nothing here can assume a light or a
 * dark background. The answer is the WCAG contrast ratio: compute it against
 * white and against black and take whichever is higher, rather than guessing a
 * lightness threshold — the ratio is what legibility is actually measured in,
 * and it lands on the right side at the boundary where a threshold does not.
 */

/**
 * The only two colours banner text is ever set to.
 *
 * Not a stylistic limit: the fill behind the words is the guild's to pick and
 * its artwork can be anything, so they stay readable only by sitting at one end
 * of the scale or the other. The database refuses anything else.
 */
export const LIGHT_TEXT = "#ffffff";
export const DARK_TEXT = "#000000";

/** `[r, g, b]` from `#rgb`, `#rrggbb`, or `#rrggbbaa`; null if it is none of those. */
const channels = (hex: string): [number, number, number] | null => {
  let value = hex.trim().replace("#", "");
  if (value.length === 3) {
    value = value
      .split("")
      .map((char) => `${char}${char}`)
      .join("");
  }
  // A trailing alpha byte is ignored: what is behind the fill is not something
  // the text has to be readable against.
  if (value.length === 8) value = value.slice(0, 6);
  if (value.length !== 6 || !/^[0-9a-f]{6}$/i.test(value)) return null;
  return [0, 2, 4].map((at) => Number.parseInt(value.slice(at, at + 2), 16)) as [
    number,
    number,
    number,
  ];
};

/** WCAG relative luminance of a colour, 0 (black) to 1 (white). */
export const relativeLuminance = (hex: string): number | null => {
  const rgb = channels(hex);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((channel) => {
    const srgb = channel / 255;
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

/**
 * The text colour that reads best on `background` — white or black, whichever
 * has the greater WCAG contrast ratio with it.
 *
 * Falls back to light text for a value it cannot parse, which is what the
 * default fill wants and what an unreadable input is least likely to ruin.
 */
export const readableTextColor = (background: string): string => {
  const luminance = relativeLuminance(background);
  if (luminance === null) return LIGHT_TEXT;
  // Contrast ratio is (lighter + 0.05) / (darker + 0.05); against white the
  // numerator is fixed at 1.05, against black the denominator is fixed at 0.05.
  const againstWhite = 1.05 / (luminance + 0.05);
  const againstBlack = (luminance + 0.05) / 0.05;
  return againstWhite >= againstBlack ? LIGHT_TEXT : DARK_TEXT;
};
