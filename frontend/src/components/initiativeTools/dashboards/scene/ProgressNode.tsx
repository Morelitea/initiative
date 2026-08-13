import { formatValue } from "@/lib/widgets/format";
import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { toneColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "progress" }>;

export function ProgressNode({ node }: { node: Node }) {
  const min = node.min ?? 0;
  const max = node.max ?? 100;
  // A zero-width range would divide by zero; treat it as complete, which is how
  // "0 of 0 tasks" actually reads.
  const span = max - min;
  const fraction = span <= 0 ? 1 : Math.min(1, Math.max(0, (node.value - min) / span));

  return (
    <div className="flex h-full w-full flex-col justify-center gap-2 p-1">
      <div className="flex items-baseline justify-between gap-2">
        {node.label && <span className="truncate font-medium text-sm">{node.label}</span>}
        <span className="shrink-0 font-semibold text-sm tabular-nums">
          {formatValue(fraction, "percent")}
        </span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={node.value}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-label={node.label}
      >
        <div
          className="h-full rounded-full transition-[width]"
          style={{ width: `${fraction * 100}%`, backgroundColor: toneColor(node.tone) }}
        />
      </div>
      {node.caption && (
        <span className="truncate text-muted-foreground text-xs">{node.caption}</span>
      )}
    </div>
  );
}
