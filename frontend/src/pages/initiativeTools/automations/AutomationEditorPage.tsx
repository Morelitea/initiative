import { useCallback, useEffect } from "react";
import { Navigate, useParams, useSearch, useRouter } from "@tanstack/react-router";
import { ReactFlowProvider } from "@xyflow/react";
import { useTranslation } from "react-i18next";
import { Loader2, Zap } from "lucide-react";

import { useAutomationFlow } from "@/hooks/useAutomationFlow";
import { useGuildPath } from "@/lib/guildUrl";
import { FlowToolbar } from "@/components/initiativeTools/automations/FlowToolbar";
import { FlowEditor } from "@/components/initiativeTools/automations/FlowEditor";
import { NodePalette } from "@/components/initiativeTools/automations/NodePalette";
import { NodeInspector } from "@/components/initiativeTools/automations/NodeInspector";
import type { FlowNodeType, FlowNodeData } from "@/components/initiativeTools/automations/types";

export function AutomationEditorPage(): React.JSX.Element {
  const { automationId } = useParams({ strict: false }) as { automationId: string };
  const search = useSearch({ strict: false }) as { initiativeId?: string };
  const router = useRouter();
  const gp = useGuildPath();
  const { t } = useTranslation("automations");

  const {
    activeFlow,
    flowNotFound,
    loadFlow,
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
  } = useAutomationFlow(search.initiativeId ?? "");

  // Load the flow on mount (or when automationId changes)
  useEffect(() => {
    if (automationId) {
      loadFlow(automationId);
    }
  }, [automationId, loadFlow]);

  const initiativeId = activeFlow?.initiativeId ?? search.initiativeId ?? "";

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: { id: string }) => {
      setSelectedNodeId(node.id);
    },
    [setSelectedNodeId]
  );

  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, [setSelectedNodeId]);

  const handleBack = useCallback(() => {
    void router.navigate({
      to: gp("/automations"),
      search: { initiativeId },
    });
  }, [router, gp, initiativeId]);

  if (!__ENABLE_AUTOMATIONS__) {
    return <Navigate to={gp("/initiatives")} replace />;
  }

  // Flow not found — show error with back button
  if (flowNotFound) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-center">
          <Zap className="text-muted-foreground h-10 w-10" />
          <p className="text-muted-foreground text-sm">{t("editor.notFound")}</p>
          <button
            onClick={handleBack}
            className="text-primary text-sm underline underline-offset-4"
          >
            {t("toolbar.back")}
          </button>
        </div>
      </div>
    );
  }

  // Show loading state while the flow is being read from storage
  if (!activeFlow) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
          <p className="text-muted-foreground text-sm">{t("editor.loading")}</p>
        </div>
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <div className="flex h-[calc(100vh-3.5rem)] flex-col">
        <FlowToolbar
          name={activeFlow.name}
          onNameChange={updateFlowName}
          onSave={saveFlow}
          isSaving={isSaving}
          enabled={activeFlow.enabled}
          onEnabledChange={updateFlowEnabled}
          onBack={handleBack}
        />
        <div className="flex flex-1 overflow-hidden">
          <NodePalette />
          <div className="relative flex-1">
            <FlowEditor
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeAdd={addNodeFromDrop}
              onNodeClick={handleNodeClick}
              onPaneClick={handlePaneClick}
            />
          </div>
        </div>
        <NodeInspector
          isOpen={!!selectedNodeId}
          onClose={() => setSelectedNodeId(null)}
          nodeId={selectedNodeId}
          nodeType={(selectedNode?.type as FlowNodeType) ?? null}
          nodeData={(selectedNode?.data as FlowNodeData) ?? null}
        />
      </div>
    </ReactFlowProvider>
  );
}
