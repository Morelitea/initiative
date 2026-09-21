import { type PixelLayout, pathFromLayout } from "./pixelLayout";

// 12x12 chunky 5-point star. Single fill — color comes from confetti palette.
const STAR_LAYOUT: PixelLayout = [
  "            ",
  "      1     ",
  "     111    ",
  " 11111111111",
  "   1111111  ",
  "    11111   ",
  "   1111111  ",
  "  111   111 ",
  " 11       11",
  "            ",
];

export const PIXEL_STAR_PATH = pathFromLayout(STAR_LAYOUT);
