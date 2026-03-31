import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps, Node } from "@xyflow/react";
import { Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { NODE_TYPE_CONFIG_MAP } from "../types";
import type { TriggerNodeData } from "../types";

type TriggerNodeType = Node<TriggerNodeData, "trigger">;

const config = NODE_TYPE_CONFIG_MAP.trigger;

function TriggerNodeComponent({ data, selected }: NodeProps<TriggerNodeType>) {
  return (
    <div
      className={cn(
        "bg-card min-w-[180px] rounded-lg border border-l-4 px-4 py-3 shadow-sm",
        config.borderClass,
        selected && "ring-primary ring-2"
      )}
    >
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 shrink-0" style={{ color: config.color }} />
        <span className="truncate text-sm font-medium">{data.label}</span>
      </div>
      <p className="text-muted-foreground mt-1 truncate text-xs">{data.eventType}</p>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-primary !border-background !h-3 !w-3 !border-2"
      />
    </div>
  );
}

export const TriggerNode = memo(TriggerNodeComponent);
