import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

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

const COIN_RIM = "#E69900";
const COIN_BASE = "#FFD700";
const COIN_HIGHLIGHT = "#FFEB7A";

interface PixelCoinProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export const PixelCoin = ({ size = 24, className, style }: PixelCoinProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(COIN_LAYOUT).map(({ x, y, char }) => {
      const fill = char === "r" ? COIN_RIM : char === "h" ? COIN_HIGHLIGHT : COIN_BASE;
      return <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={fill} />;
    })}
  </svg>
);
