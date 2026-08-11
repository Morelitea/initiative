import { useMemo } from "react";

import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { toneColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "matrix" }>;

const CELL = 12;
const GAP = 2;

/**
 * A density grid — the contribution-graph shape.
 *
 * The widget has already decided each cell's coordinates; this only paints
 * them, scaling opacity by value so a single theme color carries the intensity
 * rather than a hard-coded ramp that would fight the theme.
 */
export function MatrixNode({ node }: { node: Node }) {
  const { columns, rows, max } = useMemo(() => {
    let maxX = 0;
    let maxY = 0;
    for (const cell of node.cells) {
      if (cell.x > maxX) maxX = cell.x;
      if (cell.y > maxY) maxY = cell.y;
    }
    const ceiling = node.max ?? node.cells.reduce((peak, cell) => Math.max(peak, cell.value), 0);
    return { columns: maxX + 1, rows: maxY + 1, max: ceiling || 1 };
  }, [node]);

  const color = toneColor(node.tone);
  const labelWidth = node.yLabels?.length ? 30 : 0;

  return (
    <div className="h-full w-full overflow-auto p-1">
      <svg
        width={labelWidth + columns * (CELL + GAP)}
        height={rows * (CELL + GAP)}
        role="img"
        aria-label="Activity heatmap"
      >
        {node.yLabels?.slice(0, rows).map((label, row) => (
          <text
            key={label}
            x={0}
            y={row * (CELL + GAP) + CELL - 2}
            className="fill-muted-foreground"
            fontSize={9}
          >
            {label}
          </text>
        ))}
        {node.cells.map((cell) => (
          <rect
            key={`${cell.x}-${cell.y}`}
            x={labelWidth + cell.x * (CELL + GAP)}
            y={cell.y * (CELL + GAP)}
            width={CELL}
            height={CELL}
            rx={2}
            fill={color}
            // A floor of 8% keeps an empty day visible as a cell rather than a
            // hole in the grid.
            fillOpacity={cell.value <= 0 ? 0.08 : 0.15 + (cell.value / max) * 0.85}
          >
            {cell.label && <title>{cell.label}</title>}
          </rect>
        ))}
      </svg>
    </div>
  );
}
