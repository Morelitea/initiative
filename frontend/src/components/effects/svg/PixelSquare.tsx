import { type PixelLayout, pathFromLayout } from "./pixelLayout";

// 12x12 beveled pixel square — looks like a chunky dropped block.
const SQUARE_LAYOUT: PixelLayout = [
  "            ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "            ",
  "            ",
  "            ",
];

export const PIXEL_SQUARE_PATH = pathFromLayout(SQUARE_LAYOUT);
