import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow } from "@xyflow/react";
import type { EdgeProps, Edge } from "@xyflow/react";
import { X } from "lucide-react";

function AnimatedEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
}: EdgeProps<Edge>) {
  const { setEdges } = useReactFlow();

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const handleDelete = (event: React.MouseEvent): void => {
    event.stopPropagation();
    setEdges((eds) => eds.filter((e) => e.id !== id));
  };

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          strokeDasharray: "5,5",
        }}
      />
      <EdgeLabelRenderer>
        <div
          className="group pointer-events-auto absolute"
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
          }}
        >
          <button
            type="button"
            className="border-border bg-card text-muted-foreground hover:bg-destructive hover:text-destructive-foreground flex h-4 w-4 items-center justify-center rounded-full border opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
            onClick={handleDelete}
            aria-label="Delete edge"
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

export const AnimatedEdge = AnimatedEdgeComponent;

export const edgeTypes = { animated: AnimatedEdge } as const;
