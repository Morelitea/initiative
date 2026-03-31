import { useCallback, useEffect, useMemo, useState } from "react";
import { useNodesState, useEdgesState, addEdge } from "@xyflow/react";
import type {
  Node,
  Edge,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
  Connection,
} from "@xyflow/react";

import { getItem, setItem, removeItem } from "@/lib/storage";
import type { AutomationFlow, FlowNodeType } from "@/components/initiativeTools/automations/types";
import { NODE_TYPE_CONFIG_MAP } from "@/components/initiativeTools/automations/types";

// ---------------------------------------------------------------------------
// Storage key helpers
// ---------------------------------------------------------------------------

function flowsListKey(initiativeId: string): string {
  return `automation-flows-${initiativeId}`;
}

function flowDetailKey(flowId: string): string {
  return `automation-flow-${flowId}`;
}

// ---------------------------------------------------------------------------
// Persistence helpers
// ---------------------------------------------------------------------------

function readFlowsList(initiativeId: string): AutomationFlow[] {
  const raw = getItem(flowsListKey(initiativeId));
  if (!raw) return [];
  try {
    return JSON.parse(raw) as AutomationFlow[];
  } catch {
    return [];
  }
}

function writeFlowsList(initiativeId: string, flows: AutomationFlow[]): void {
  setItem(flowsListKey(initiativeId), JSON.stringify(flows));
}

function readFlowDetail(flowId: string): AutomationFlow | null {
  const raw = getItem(flowDetailKey(flowId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AutomationFlow;
  } catch {
    return null;
  }
}

function writeFlowDetail(flow: AutomationFlow): void {
  setItem(flowDetailKey(flow.id), JSON.stringify(flow));
}

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export interface UseAutomationFlowReturn {
  // List management
  flows: AutomationFlow[];
  createFlow: (name: string, description?: string) => string;
  deleteFlow: (flowId: string) => void;

  // Active flow editing
  activeFlow: AutomationFlow | null;
  flowNotFound: boolean;
  loadFlow: (flowId: string) => void;
  closeFlow: () => void;

  // xyflow state (only valid when activeFlow is set)
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;

  // Drop handler for palette
  addNodeFromDrop: (type: FlowNodeType, position: { x: number; y: number }) => void;

  // Save
  saveFlow: () => void;
  isSaving: boolean;

  // Metadata
  updateFlowName: (name: string) => void;
  updateFlowEnabled: (enabled: boolean) => void;

  // Selection
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  selectedNode: Node | null;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAutomationFlow(initiativeId: string): UseAutomationFlowReturn {
  // -- List state --
  const [flows, setFlows] = useState<AutomationFlow[]>(() => readFlowsList(initiativeId));

  // Re-read from storage when initiativeId changes
  useEffect(() => {
    setFlows(readFlowsList(initiativeId));
  }, [initiativeId]);

  // -- Active flow metadata --
  const [activeFlow, setActiveFlow] = useState<AutomationFlow | null>(null);
  const [flowNotFound, setFlowNotFound] = useState(false);

  // -- xyflow state --
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // -- Save feedback --
  const [isSaving, setIsSaving] = useState(false);

  // -- Selection --
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  );

  // -----------------------------------------------------------------------
  // List management
  // -----------------------------------------------------------------------

  const createFlow = useCallback(
    (name: string, description?: string): string => {
      const id = crypto.randomUUID();
      const now = new Date().toISOString();

      const defaultTriggerNode: Node = {
        id: crypto.randomUUID(),
        type: "trigger",
        position: { x: 250, y: 50 },
        data: NODE_TYPE_CONFIG_MAP.trigger.defaultData(),
      };

      const newFlow: AutomationFlow = {
        id,
        name,
        description,
        initiativeId,
        nodes: [defaultTriggerNode],
        edges: [],
        enabled: false,
        createdAt: now,
        updatedAt: now,
      };

      // Persist detail
      writeFlowDetail(newFlow);

      // Update list (metadata only: strip nodes/edges to avoid storage bloat)
      const listEntry: AutomationFlow = { ...newFlow, nodes: [], edges: [] };
      setFlows((prev) => {
        const updated = [...prev, listEntry];
        writeFlowsList(initiativeId, updated);
        return updated;
      });

      return id;
    },
    [initiativeId]
  );

  const deleteFlow = useCallback(
    (flowId: string) => {
      // If the deleted flow is currently active, close it
      if (activeFlow?.id === flowId) {
        setActiveFlow(null);
        setNodes([]);
        setEdges([]);
        setSelectedNodeId(null);
      }

      setFlows((prev) => {
        const updated = prev.filter((f) => f.id !== flowId);
        writeFlowsList(initiativeId, updated);
        return updated;
      });

      removeItem(flowDetailKey(flowId));
    },
    [initiativeId, activeFlow, setNodes, setEdges]
  );

  // -----------------------------------------------------------------------
  // Active flow editing
  // -----------------------------------------------------------------------

  const loadFlow = useCallback(
    (flowId: string) => {
      const flow = readFlowDetail(flowId);
      if (!flow) {
        setFlowNotFound(true);
        return;
      }

      setFlowNotFound(false);
      setActiveFlow(flow);
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setSelectedNodeId(null);
    },
    [setNodes, setEdges]
  );

  const closeFlow = useCallback(() => {
    setActiveFlow(null);
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
  }, [setNodes, setEdges]);

  // -----------------------------------------------------------------------
  // Connection handler
  // -----------------------------------------------------------------------

  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge({ ...connection, type: "animated", animated: true }, eds));
    },
    [setEdges]
  );

  // -----------------------------------------------------------------------
  // Drop handler for palette
  // -----------------------------------------------------------------------

  const addNodeFromDrop = useCallback(
    (type: FlowNodeType, position: { x: number; y: number }) => {
      const config = NODE_TYPE_CONFIG_MAP[type];
      const newNode: Node = {
        id: crypto.randomUUID(),
        type,
        position,
        data: config.defaultData(),
      };
      setNodes((nds) => [...nds, newNode]);
    },
    [setNodes]
  );

  // -----------------------------------------------------------------------
  // Save
  // -----------------------------------------------------------------------

  const saveFlow = useCallback(() => {
    if (!activeFlow) return;

    setIsSaving(true);

    const now = new Date().toISOString();
    const updatedFlow: AutomationFlow = {
      ...activeFlow,
      nodes,
      edges,
      updatedAt: now,
    };

    // Persist full detail
    writeFlowDetail(updatedFlow);

    // Update metadata in the list (strip nodes/edges to avoid storage bloat)
    setFlows((prev) => {
      const listEntry: AutomationFlow = {
        ...updatedFlow,
        nodes: [],
        edges: [],
      };
      const updated = prev.map((f) => (f.id === updatedFlow.id ? listEntry : f));
      writeFlowsList(initiativeId, updated);
      return updated;
    });

    setActiveFlow(updatedFlow);

    // Brief saving indicator for UI feedback
    setTimeout(() => setIsSaving(false), 400);
  }, [activeFlow, nodes, edges, initiativeId]);

  // -----------------------------------------------------------------------
  // Metadata
  // -----------------------------------------------------------------------

  const updateFlowName = useCallback((name: string) => {
    setActiveFlow((prev) => (prev ? { ...prev, name } : null));
  }, []);

  const updateFlowEnabled = useCallback((enabled: boolean) => {
    setActiveFlow((prev) => (prev ? { ...prev, enabled } : null));
  }, []);

  // -----------------------------------------------------------------------
  // Return
  // -----------------------------------------------------------------------

  return {
    flows,
    createFlow,
    deleteFlow,

    activeFlow,
    flowNotFound,
    loadFlow,
    closeFlow,

    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,

    addNodeFromDrop,

    saveFlow,
    isSaving,

    updateFlowName,
    updateFlowEnabled,

    selectedNodeId,
    setSelectedNodeId,
    selectedNode,
  };
}
