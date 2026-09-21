import { type PixelLayout, pathFromLayout } from "./pixelLayout";

// 12x12 gold coin. r = rim (dark), 1 = coin face base, h = highlight.
const COIN_LAYOUT: PixelLayout = [
  "            ",
  "    rrrr    ",
  "  rr1111rr  ",
  "  r111h11r  ",
  " r11111111r ",
  " r1h111111r ",
  " r11111111r ",
  " r11111h11r ",
  " r111111111r",
  "  r111111r  ",
  "  rr1111rr  ",
  "    rrrr    ",
];

// Path uses *all* filled cells (rim + face + highlight) so the canvas-confetti
// shape silhouette includes the rim. Color differentiation only matters for
// the React component below; canvas-confetti recolors the whole path with one
// fill color per particle anyway.
export const PIXEL_COIN_PATH = pathFromLayout(COIN_LAYOUT);
