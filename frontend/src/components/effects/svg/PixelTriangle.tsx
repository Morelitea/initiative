import { type PixelLayout, pathFromLayout } from "./pixelLayout";

// 12x12 chunky upward triangle.
const TRIANGLE_LAYOUT: PixelLayout = [
  "            ",
  "      1     ",
  "     111    ",
  "     111    ",
  "    11111   ",
  "    11111   ",
  "   1111111  ",
  "   1111111  ",
  "  111111111 ",
  "  111111111 ",
  " 11111111111",
  "            ",
];

export const PIXEL_TRIANGLE_PATH = pathFromLayout(TRIANGLE_LAYOUT);
