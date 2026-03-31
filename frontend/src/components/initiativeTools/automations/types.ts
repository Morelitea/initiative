import type { LucideIcon } from "lucide-react";
import { GitBranch, Repeat, Timer, Wrench, Zap } from "lucide-react";
import type { Node, Edge } from "@xyflow/react";

// ---------------------------------------------------------------------------
// Node type discriminator
// ---------------------------------------------------------------------------

export type FlowNodeType = "trigger" | "action" | "condition" | "delay" | "loop";

// ---------------------------------------------------------------------------
// Per-node data interfaces
// ---------------------------------------------------------------------------

export interface TriggerNodeData {
  label: string;
  eventType: string;
  [key: string]: unknown;
}

export interface ActionNodeData {
  label: string;
  actionType: string;
  config: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ConditionNodeData {
  label: string;
  field: string;
  operator: string;
  value: string;
  [key: string]: unknown;
}

export interface DelayNodeData {
  label: string;
  duration: number;
  unit: "seconds" | "minutes" | "hours" | "days";
  [key: string]: unknown;
}

export interface LoopNodeData {
  label: string;
  collectionField: string;
  [key: string]: unknown;
}

export type FlowNodeData =
  | TriggerNodeData
  | ActionNodeData
  | ConditionNodeData
  | DelayNodeData
  | LoopNodeData;

// ---------------------------------------------------------------------------
// Flow model (persisted to localStorage, later to backend)
// ---------------------------------------------------------------------------

export interface AutomationFlow {
  id: string;
  name: string;
  description?: string;
  initiativeId: string;
  nodes: Node[];
  edges: Edge[];
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Node type configuration (shared by palette + node renderers)
// ---------------------------------------------------------------------------

export interface NodeTypeConfig {
  type: FlowNodeType;
  icon: LucideIcon;
  color: string;
  borderClass: string;
  labelKey: string;
  descriptionKey: string;
  defaultData: () => FlowNodeData;
}

export const NODE_TYPE_CONFIGS: NodeTypeConfig[] = [
  {
    type: "trigger",
    icon: Zap,
    color: "#f59e0b",
    borderClass: "border-l-amber-500",
    labelKey: "automations:nodeTypes.trigger",
    descriptionKey: "automations:nodeTypes.triggerDescription",
    defaultData: () => ({ label: "Trigger", eventType: "task_created" }),
  },
  {
    type: "action",
    icon: Wrench,
    color: "#3b82f6",
    borderClass: "border-l-blue-500",
    labelKey: "automations:nodeTypes.action",
    descriptionKey: "automations:nodeTypes.actionDescription",
    defaultData: () => ({ label: "Action", actionType: "send_webhook", config: {} }),
  },
  {
    type: "condition",
    icon: GitBranch,
    color: "#8b5cf6",
    borderClass: "border-l-purple-500",
    labelKey: "automations:nodeTypes.condition",
    descriptionKey: "automations:nodeTypes.conditionDescription",
    defaultData: () => ({ label: "Condition", field: "", operator: "equals", value: "" }),
  },
  {
    type: "delay",
    icon: Timer,
    color: "#f97316",
    borderClass: "border-l-orange-500",
    labelKey: "automations:nodeTypes.delay",
    descriptionKey: "automations:nodeTypes.delayDescription",
    defaultData: () => ({ label: "Delay", duration: 5, unit: "minutes" as const }),
  },
  {
    type: "loop",
    icon: Repeat,
    color: "#10b981",
    borderClass: "border-l-green-500",
    labelKey: "automations:nodeTypes.loop",
    descriptionKey: "automations:nodeTypes.loopDescription",
    defaultData: () => ({ label: "Loop", collectionField: "" }),
  },
];

export const NODE_TYPE_CONFIG_MAP = Object.fromEntries(
  NODE_TYPE_CONFIGS.map((c) => [c.type, c])
) as Record<FlowNodeType, NodeTypeConfig>;

// ---------------------------------------------------------------------------
// Inspector dropdown options
// ---------------------------------------------------------------------------

export const TRIGGER_EVENT_OPTIONS = [
  { value: "task_created", labelKey: "automations:triggerEvents.task_created" },
  { value: "task_updated", labelKey: "automations:triggerEvents.task_updated" },
  { value: "status_changed", labelKey: "automations:triggerEvents.status_changed" },
  { value: "assignee_changed", labelKey: "automations:triggerEvents.assignee_changed" },
  { value: "due_date_reached", labelKey: "automations:triggerEvents.due_date_reached" },
];

export const ACTION_TYPE_OPTIONS = [
  { value: "send_webhook", labelKey: "automations:actionTypes.send_webhook" },
  { value: "update_task", labelKey: "automations:actionTypes.update_task" },
  { value: "send_notification", labelKey: "automations:actionTypes.send_notification" },
  { value: "add_tag", labelKey: "automations:actionTypes.add_tag" },
  { value: "remove_tag", labelKey: "automations:actionTypes.remove_tag" },
  { value: "move_to_project", labelKey: "automations:actionTypes.move_to_project" },
];

export const CONDITION_OPERATOR_OPTIONS = [
  { value: "equals", labelKey: "automations:conditionOperators.equals" },
  { value: "not_equals", labelKey: "automations:conditionOperators.not_equals" },
  { value: "contains", labelKey: "automations:conditionOperators.contains" },
  { value: "greater_than", labelKey: "automations:conditionOperators.greater_than" },
  { value: "less_than", labelKey: "automations:conditionOperators.less_than" },
];

export const DELAY_UNIT_OPTIONS = [
  { value: "seconds", labelKey: "automations:delayUnits.seconds" },
  { value: "minutes", labelKey: "automations:delayUnits.minutes" },
  { value: "hours", labelKey: "automations:delayUnits.hours" },
  { value: "days", labelKey: "automations:delayUnits.days" },
];
