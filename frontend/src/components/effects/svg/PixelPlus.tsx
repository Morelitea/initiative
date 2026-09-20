import { type PixelLayout, pathFromLayout } from "./pixelLayout";

// 12x12 fat plus / cross.
const PLUS_LAYOUT: PixelLayout = [
  "            ",
  "    1111    ",
  "    1111    ",
  "    1111    ",
  " 1111111111 ",
  " 1111111111 ",
  " 1111111111 ",
  "    1111    ",
  "    1111    ",
  "    1111    ",
  "            ",
  "            ",
];

export const PIXEL_PLUS_PATH = pathFromLayout(PLUS_LAYOUT);
