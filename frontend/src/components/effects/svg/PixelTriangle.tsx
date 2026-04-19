import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

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

interface PixelTriangleProps {
  size?: number;
  color?: string;
  className?: string;
  style?: CSSProperties;
}

export const PixelTriangle = ({
  size = 24,
  color = "#A78BFA",
  className,
  style,
}: PixelTriangleProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(TRIANGLE_LAYOUT).map(({ x, y }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={color} />
    ))}
  </svg>
);
