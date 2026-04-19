// Tiny helpers for the pixel-grid SVG components in this folder.
// Each SVG is a string-array of "rows", where any non-space character
// is a filled cell. Multiple non-space chars allow multi-color shading.
//
// `pathFromLayout` builds an SVG path string suitable for
// `confetti.shapeFromPath({ path })`. The path uses 1x1 squares per cell
// — fine for canvas-confetti since it samples shapes onto a small canvas
// and the chunky pixel look is the goal anyway.

export type PixelLayout = readonly string[];

export const pathFromLayout = (layout: PixelLayout): string =>
  layout
    .flatMap((row, y) =>
      Array.from(row).flatMap((cell, x) => (cell !== " " ? [`M${x} ${y}h1v1h-1z`] : []))
    )
    .join(" ");

// Walk a layout and yield one `{x,y,char}` per filled cell.
export const cellsFromLayout = (
  layout: PixelLayout
): ReadonlyArray<{ x: number; y: number; char: string }> => {
  const cells: { x: number; y: number; char: string }[] = [];
  for (let y = 0; y < layout.length; y++) {
    const row = layout[y];
    for (let x = 0; x < row.length; x++) {
      const char = row[x];
      if (char !== " ") cells.push({ x, y, char });
    }
  }
  return cells;
};
