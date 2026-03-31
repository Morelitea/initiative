import type { NodeTypes, EdgeTypes } from "@xyflow/react";
import { TriggerNode } from "./TriggerNode";
import { ActionNode } from "./ActionNode";
import { ConditionNode } from "./ConditionNode";
import { DelayNode } from "./DelayNode";
import { LoopNode } from "./LoopNode";
import { AnimatedEdge } from "../edges/AnimatedEdge";

export const nodeTypes: NodeTypes = {
  trigger: TriggerNode,
  action: ActionNode,
  condition: ConditionNode,
  delay: DelayNode,
  loop: LoopNode,
};

export const edgeTypes: EdgeTypes = {
  animated: AnimatedEdge,
};
