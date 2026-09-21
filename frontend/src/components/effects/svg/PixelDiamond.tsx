import { type PixelLayout, pathFromLayout } from "./pixelLayout";

// 12x12 pixel rhombus / diamond.
const DIAMOND_LAYOUT: PixelLayout = [
  "            ",
  "     11     ",
  "    1111    ",
  "   111111   ",
  "  11111111  ",
  " 1111111111 ",
  "  11111111  ",
  "   111111   ",
  "    1111    ",
  "     11     ",
  "            ",
  "            ",
];

export const PIXEL_DIAMOND_PATH = pathFromLayout(DIAMOND_LAYOUT);
