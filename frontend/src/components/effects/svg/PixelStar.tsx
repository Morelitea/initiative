import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

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

interface PixelStarProps {
  size?: number;
  color?: string;
  className?: string;
  style?: CSSProperties;
}

export const PixelStar = ({ size = 24, color = "#FBBF24", className, style }: PixelStarProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(STAR_LAYOUT).map(({ x, y }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={color} />
    ))}
  </svg>
);
