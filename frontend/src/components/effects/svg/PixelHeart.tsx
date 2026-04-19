import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

// 11x9 grid (1 = base red, h = highlight). Pure pixel grid, no anti-alias.
// Bilaterally symmetric around col 5 / row 4 so the SVG's geometric center
// is the heart's visual center — important for the floater overlay.
const HEART_LAYOUT: PixelLayout = [
  "  11   11  ",
  " 1hh1 1hh1 ",
  "11111111111",
  "11111111111",
  " 111111111 ",
  "  1111111  ",
  "   11111   ",
  "    111    ",
  "     1     ",
];

const HEART_VIEW_W = HEART_LAYOUT[0].length;
const HEART_VIEW_H = HEART_LAYOUT.length;

const RED_BASE = "#DC2626"; // red-600
const RED_HIGHLIGHT = "#F87171"; // red-400

export const PIXEL_HEART_PATH = pathFromLayout(HEART_LAYOUT);

interface PixelHeartProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export const PixelHeart = ({ size = 64, className, style }: PixelHeartProps) => (
  <svg
    width={size}
    height={size}
    viewBox={`0 0 ${HEART_VIEW_W} ${HEART_VIEW_H}`}
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(HEART_LAYOUT).map(({ x, y, char }) => (
      <rect
        key={`${x},${y}`}
        x={x}
        y={y}
        width="1"
        height="1"
        fill={char === "h" ? RED_HIGHLIGHT : RED_BASE}
      />
    ))}
  </svg>
);
