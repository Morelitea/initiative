import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps, Node } from "@xyflow/react";
import { Timer } from "lucide-react";
import { cn } from "@/lib/utils";
import { NODE_TYPE_CONFIG_MAP } from "../types";
import type { DelayNodeData } from "../types";

type DelayNodeType = Node<DelayNodeData, "delay">;

const config = NODE_TYPE_CONFIG_MAP.delay;

function DelayNodeComponent({ data, selected }: NodeProps<DelayNodeType>) {
  return (
    <div
      className={cn(
        "bg-card min-w-[180px] rounded-lg border border-l-4 px-4 py-3 shadow-sm",
        config.borderClass,
        selected && "ring-primary ring-2"
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-primary !border-background !h-3 !w-3 !border-2"
      />

      <div className="flex items-center gap-2">
        <Timer className="h-4 w-4 shrink-0" style={{ color: config.color }} />
        <span className="truncate text-sm font-medium">{data.label}</span>
      </div>
      <p className="text-muted-foreground mt-1 truncate text-xs">
        {data.duration} {data.unit}
      </p>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-primary !border-background !h-3 !w-3 !border-2"
      />
    </div>
  );
}

export const DelayNode = memo(DelayNodeComponent);
