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
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  useListAutomationsApiV1AutomationsGet,
  useCreateAutomationApiV1AutomationsPost,
  useDeleteAutomationApiV1AutomationsFlowIdDelete,
  useReadAutomationApiV1AutomationsFlowIdGet,
  useUpdateAutomationApiV1AutomationsFlowIdPut,
  getListAutomationsApiV1AutomationsGetQueryKey,
  getReadAutomationApiV1AutomationsFlowIdGetQueryKey,
} from "@/api/generated/automations/automations";
import type {
  AutomationFlowListItem,
  AutomationFlowRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { FlowNodeType } from "@/components/initiativeTools/automations/types";
import { NODE_TYPE_CONFIG_MAP } from "@/components/initiativeTools/automations/types";
import { getErrorMessage } from "@/lib/errorMessage";

// ---------------------------------------------------------------------------
// Helpers to safely cast flow_data <-> Node[]/Edge[]
// ---------------------------------------------------------------------------

interface FlowData {
  nodes: Node[];
  edges: Edge[];
}

function parseFlowData(raw: { [key: string]: unknown }): FlowData {
  const nodes = Array.isArray(raw.nodes) ? (raw.nodes as Node[]) : [];
  const edges = Array.isArray(raw.edges) ? (raw.edges as Edge[]) : [];
  return { nodes, edges };
}

function serializeFlowData(nodes: Node[], edges: Edge[]): { [key: string]: unknown } {
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Return types
// ---------------------------------------------------------------------------

export interface UseAutomationFlowsReturn {
  flows: AutomationFlowListItem[];
  isLoading: boolean;
  createFlow: (name: string, description?: string) => Promise<number>;
  deleteFlow: (flowId: number) => void;
}

export interface UseAutomationEditorReturn {
  flow: AutomationFlowRead | null;
  isLoading: boolean;
  flowNotFound: boolean;
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  addNodeFromDrop: (type: FlowNodeType, position: { x: number; y: number }) => void;
  saveFlow: () => void;
  isSaving: boolean;
  updateFlowName: (name: string) => void;
  updateFlowEnabled: (enabled: boolean) => void;
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  selectedNode: Node | null;
}

// ---------------------------------------------------------------------------
// useAutomationFlows — list page hook
// ---------------------------------------------------------------------------

export function useAutomationFlows(initiativeId: number): UseAutomationFlowsReturn {
  const { t } = useTranslation("automations");
  const queryClient = useQueryClient();

  const { data, isLoading } = useListAutomationsApiV1AutomationsGet({
    initiative_id: initiativeId,
  });

  const flows = data?.items ?? [];

  const createMutation = useCreateAutomationApiV1AutomationsPost({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListAutomationsApiV1AutomationsGetQueryKey(),
        });
      },
      onError: (error) => {
        toast.error(getErrorMessage(error, "automations:createError"));
      },
    },
  });

  const deleteMutation = useDeleteAutomationApiV1AutomationsFlowIdDelete({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListAutomationsApiV1AutomationsGetQueryKey(),
        });
        toast.success(t("deleteSuccess"));
      },
      onError: (error) => {
        toast.error(getErrorMessage(error, "automations:deleteError"));
      },
    },
  });

  const createFlow = useCallback(
    async (name: string, description?: string): Promise<number> => {
      const defaultTriggerNode: Node = {
        id: crypto.randomUUID(),
        type: "trigger",
        position: { x: 250, y: 50 },
        data: NODE_TYPE_CONFIG_MAP.trigger.defaultData(),
      };

      const result = await createMutation.mutateAsync({
        data: {
          name,
          description: description ?? null,
          initiative_id: initiativeId,
          flow_data: serializeFlowData([defaultTriggerNode], []),
          enabled: false,
        },
      });

      return result.id;
    },
    [createMutation, initiativeId]
  );

  const deleteFlow = useCallback(
    (flowId: number) => {
      deleteMutation.mutate({ flowId });
    },
    [deleteMutation]
  );

  return {
    flows,
    isLoading,
    createFlow,
    deleteFlow,
  };
}

// ---------------------------------------------------------------------------
// useAutomationEditor — editor page hook
// ---------------------------------------------------------------------------

export function useAutomationEditor(flowId: number): UseAutomationEditorReturn {
  const { t } = useTranslation("automations");
  const queryClient = useQueryClient();

  // -- Fetch the flow from the API --
  const {
    data: flow,
    isLoading,
    isError,
  } = useReadAutomationApiV1AutomationsFlowIdGet(flowId, {
    query: {
      enabled: flowId > 0,
    },
  });

  const flowNotFound = isError || (flowId > 0 && !isLoading && !flow);

  // -- xyflow state --
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // -- Pending metadata changes (applied on save) --
  const [pendingName, setPendingName] = useState<string | null>(null);
  const [pendingEnabled, setPendingEnabled] = useState<boolean | null>(null);

  // -- Selection --
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  );

  // Sync xyflow state when the API returns (initial load or refetch)
  useEffect(() => {
    if (flow) {
      const { nodes: flowNodes, edges: flowEdges } = parseFlowData(flow.flow_data);
      setNodes(flowNodes);
      setEdges(flowEdges);
      setSelectedNodeId(null);
      // Reset pending metadata when fresh data arrives
      setPendingName(null);
      setPendingEnabled(null);
    }
  }, [flow, setNodes, setEdges]);

  // -- Connection handler --
  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge({ ...connection, type: "animated", animated: true }, eds));
    },
    [setEdges]
  );

  // -- Drop handler --
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

  // -- Save mutation --
  const updateMutation = useUpdateAutomationApiV1AutomationsFlowIdPut({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListAutomationsApiV1AutomationsGetQueryKey(),
        });
        void queryClient.invalidateQueries({
          queryKey: getReadAutomationApiV1AutomationsFlowIdGetQueryKey(flowId),
        });
        toast.success(t("saveSuccess"));
      },
      onError: (error) => {
        toast.error(getErrorMessage(error, "automations:saveError"));
      },
    },
  });

  const saveFlow = useCallback(() => {
    if (!flow) return;

    updateMutation.mutate({
      flowId: flow.id,
      data: {
        ...(pendingName != null ? { name: pendingName } : {}),
        ...(pendingEnabled != null ? { enabled: pendingEnabled } : {}),
        flow_data: serializeFlowData(nodes, edges),
      },
    });
  }, [flow, nodes, edges, pendingName, pendingEnabled, updateMutation]);

  // -- Metadata setters (optimistic local state, persisted on save) --
  const updateFlowName = useCallback((name: string) => {
    setPendingName(name);
  }, []);

  const updateFlowEnabled = useCallback((enabled: boolean) => {
    setPendingEnabled(enabled);
  }, []);

  // Build a "view" of the flow that includes pending metadata overrides.
  // This lets the toolbar display the user's edits before they hit save.
  const flowWithPending = useMemo((): AutomationFlowRead | null => {
    if (!flow) return null;
    return {
      ...flow,
      ...(pendingName != null ? { name: pendingName } : {}),
      ...(pendingEnabled != null ? { enabled: pendingEnabled } : {}),
    };
  }, [flow, pendingName, pendingEnabled]);

  return {
    flow: flowWithPending,
    isLoading,
    flowNotFound: !!flowNotFound,
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNodeFromDrop,
    saveFlow,
    isSaving: updateMutation.isPending,
    updateFlowName,
    updateFlowEnabled,
    selectedNodeId,
    setSelectedNodeId,
    selectedNode,
  };
}
