import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

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

interface PixelPlusProps {
  size?: number;
  color?: string;
  className?: string;
  style?: CSSProperties;
}

export const PixelPlus = ({ size = 24, color = "#34D399", className, style }: PixelPlusProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(PLUS_LAYOUT).map(({ x, y }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={color} />
    ))}
  </svg>
);
