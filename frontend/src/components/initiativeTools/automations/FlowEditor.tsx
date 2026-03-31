import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useReactFlow,
} from "@xyflow/react";
import type {
  Node,
  Edge,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
  Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { nodeTypes } from "./nodes/nodeTypes";
import { edgeTypes } from "./edges/AnimatedEdge";
import type { FlowNodeType } from "./types";

interface FlowEditorProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  onNodeAdd: (type: FlowNodeType, position: { x: number; y: number }) => void;
  onNodeClick?: (event: React.MouseEvent, node: Node) => void;
  onPaneClick?: () => void;
}

export function FlowEditor({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeAdd,
  onNodeClick,
  onPaneClick,
}: FlowEditorProps) {
  const { t } = useTranslation("automations");
  const { screenToFlowPosition } = useReactFlow();

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => connection.source !== connection.target,
    []
  );

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/reactflow") as FlowNodeType;
      if (!type) return;
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      onNodeAdd(type, position);
    },
    [screenToFlowPosition, onNodeAdd]
  );

  return (
    <div className="relative h-full w-full [&_.react-flow__controls_button]:border [&_.react-flow__controls_button]:border-[hsl(var(--border))] [&_.react-flow__controls_button]:bg-[hsl(var(--card))] [&_.react-flow__controls_button]:text-[hsl(var(--foreground))] [&_.react-flow__controls_button:hover]:bg-[hsl(var(--accent))] [&_.react-flow__minimap]:bg-[hsl(var(--card))]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        isValidConnection={isValidConnection}
        deleteKeyCode="Delete"
        selectionKeyCode="Shift"
        fitView
      >
        <MiniMap />
        <Controls />
        <Background variant={BackgroundVariant.Dots} />

        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <p className="text-muted-foreground text-lg">{t("emptyCanvas")}</p>
          </div>
        )}
      </ReactFlow>
    </div>
  );
}
