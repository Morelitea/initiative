import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps, Node } from "@xyflow/react";
import { Repeat } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { NODE_TYPE_CONFIG_MAP } from "../types";
import type { LoopNodeData } from "../types";

type LoopNodeType = Node<LoopNodeData, "loop">;

const config = NODE_TYPE_CONFIG_MAP.loop;

function LoopNodeComponent({ data, selected }: NodeProps<LoopNodeType>) {
  const { t } = useTranslation("automations");

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
        <Repeat className="h-4 w-4 shrink-0" style={{ color: config.color }} />
        <span className="truncate text-sm font-medium">{data.label}</span>
      </div>
      <p className="text-muted-foreground mt-1 truncate text-xs">
        {data.collectionField || t("defaults.noCollectionSet")}
      </p>

      {/* Body branch */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="body"
        style={{ left: "33%" }}
        className="!bg-primary !border-background !h-3 !w-3 !border-2"
      />
      <span
        className="text-muted-foreground absolute text-[10px]"
        style={{ bottom: -16, left: "33%", transform: "translateX(-50%)" }}
      >
        {t("handles.body")}
      </span>

      {/* Done branch */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="done"
        style={{ left: "66%" }}
        className="!bg-primary !border-background !h-3 !w-3 !border-2"
      />
      <span
        className="text-muted-foreground absolute text-[10px]"
        style={{ bottom: -16, left: "66%", transform: "translateX(-50%)" }}
      >
        {t("handles.done")}
      </span>
    </div>
  );
}

export const LoopNode = memo(LoopNodeComponent);
