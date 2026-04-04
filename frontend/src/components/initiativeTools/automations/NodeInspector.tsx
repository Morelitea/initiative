import { useTranslation } from "react-i18next";
import { useReactFlow } from "@xyflow/react";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";

import type {
  FlowNodeType,
  FlowNodeData,
  TriggerNodeData,
  ActionNodeData,
  ConditionNodeData,
  DelayNodeData,
  LoopNodeData,
} from "./types";
import {
  NODE_TYPE_CONFIG_MAP,
  TRIGGER_EVENT_OPTIONS,
  ACTION_TYPE_OPTIONS,
  CONDITION_OPERATOR_OPTIONS,
  DELAY_UNIT_OPTIONS,
} from "./types";

interface NodeInspectorProps {
  isOpen: boolean;
  onClose: () => void;
  nodeId: string | null;
  nodeType: FlowNodeType | null;
  nodeData: FlowNodeData | null;
}

export function NodeInspector({ isOpen, onClose, nodeId, nodeType, nodeData }: NodeInspectorProps) {
  const { t } = useTranslation("automations");
  const { updateNodeData } = useReactFlow();

  if (!nodeId || !nodeType || !nodeData) {
    return (
      <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <SheetContent side="right">
          <SheetHeader>
            <SheetTitle>{t("inspector.title")}</SheetTitle>
          </SheetHeader>
          <p className="text-muted-foreground mt-4 text-sm">{t("inspector.noSelection")}</p>
        </SheetContent>
      </Sheet>
    );
  }

  const config = NODE_TYPE_CONFIG_MAP[nodeType];
  const Icon = config.icon;

  const handleUpdate = (updates: Partial<FlowNodeData>) => {
    updateNodeData(nodeId, updates);
  };

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <div
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
              style={{ backgroundColor: config.color + "20" }}
            >
              <Icon className="h-4 w-4" style={{ color: config.color }} />
            </div>
            <div className="min-w-0">
              <SheetTitle>{t("inspector.title")}</SheetTitle>
              <Badge variant="outline" className="mt-1">
                {t(config.labelKey as never)}
              </Badge>
            </div>
          </div>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          {/* Common: Label field */}
          <div className="space-y-2">
            <Label htmlFor="node-label">{t("inspector.label")}</Label>
            <Input
              id="node-label"
              value={nodeData.label}
              onChange={(e) => handleUpdate({ label: e.target.value })}
            />
          </div>

          <Separator />

          {/* Type-specific fields */}
          {nodeType === "trigger" && (
            <TriggerFields data={nodeData as TriggerNodeData} onUpdate={handleUpdate} />
          )}
          {nodeType === "action" && (
            <ActionFields data={nodeData as ActionNodeData} onUpdate={handleUpdate} />
          )}
          {nodeType === "condition" && (
            <ConditionFields data={nodeData as ConditionNodeData} onUpdate={handleUpdate} />
          )}
          {nodeType === "delay" && (
            <DelayFields data={nodeData as DelayNodeData} onUpdate={handleUpdate} />
          )}
          {nodeType === "loop" && (
            <LoopFields data={nodeData as LoopNodeData} onUpdate={handleUpdate} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Type-specific field sections
// ---------------------------------------------------------------------------

interface TriggerFieldsProps {
  data: TriggerNodeData;
  onUpdate: (updates: Partial<TriggerNodeData>) => void;
}

function TriggerFields({ data, onUpdate }: TriggerFieldsProps) {
  const { t } = useTranslation("automations");

  return (
    <div className="space-y-2">
      <Label htmlFor="trigger-event-type">{t("inspector.eventType")}</Label>
      <Select value={data.eventType} onValueChange={(value) => onUpdate({ eventType: value })}>
        <SelectTrigger id="trigger-event-type">
          <SelectValue placeholder={t("inspector.selectEventType")} />
        </SelectTrigger>
        <SelectContent>
          {TRIGGER_EVENT_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {t(option.labelKey as never)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

interface ActionFieldsProps {
  data: ActionNodeData;
  onUpdate: (updates: Partial<ActionNodeData>) => void;
}

function ActionFields({ data, onUpdate }: ActionFieldsProps) {
  const { t } = useTranslation("automations");

  return (
    <div className="space-y-2">
      <Label htmlFor="action-type">{t("inspector.actionType")}</Label>
      <Select value={data.actionType} onValueChange={(value) => onUpdate({ actionType: value })}>
        <SelectTrigger id="action-type">
          <SelectValue placeholder={t("inspector.selectActionType")} />
        </SelectTrigger>
        <SelectContent>
          {ACTION_TYPE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {t(option.labelKey as never)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

interface ConditionFieldsProps {
  data: ConditionNodeData;
  onUpdate: (updates: Partial<ConditionNodeData>) => void;
}

function ConditionFields({ data, onUpdate }: ConditionFieldsProps) {
  const { t } = useTranslation("automations");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="condition-field">{t("inspector.field")}</Label>
        <Input
          id="condition-field"
          value={data.field}
          onChange={(e) => onUpdate({ field: e.target.value })}
          placeholder={t("inspector.fieldPlaceholder")}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="condition-operator">{t("inspector.operator")}</Label>
        <Select value={data.operator} onValueChange={(value) => onUpdate({ operator: value })}>
          <SelectTrigger id="condition-operator">
            <SelectValue placeholder={t("inspector.selectOperator")} />
          </SelectTrigger>
          <SelectContent>
            {CONDITION_OPERATOR_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {t(option.labelKey as never)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="condition-value">{t("inspector.value")}</Label>
        <Input
          id="condition-value"
          value={data.value}
          onChange={(e) => onUpdate({ value: e.target.value })}
          placeholder={t("inspector.valuePlaceholder")}
        />
      </div>
    </div>
  );
}

interface DelayFieldsProps {
  data: DelayNodeData;
  onUpdate: (updates: Partial<DelayNodeData>) => void;
}

function DelayFields({ data, onUpdate }: DelayFieldsProps) {
  const { t } = useTranslation("automations");

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="delay-duration">{t("inspector.duration")}</Label>
        <Input
          id="delay-duration"
          type="number"
          min={0}
          value={data.duration}
          onChange={(e) => onUpdate({ duration: Math.max(0, Number(e.target.value)) })}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="delay-unit">{t("inspector.unit")}</Label>
        <Select
          value={data.unit}
          onValueChange={(value) => onUpdate({ unit: value as DelayNodeData["unit"] })}
        >
          <SelectTrigger id="delay-unit">
            <SelectValue placeholder={t("inspector.selectUnit")} />
          </SelectTrigger>
          <SelectContent>
            {DELAY_UNIT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {t(option.labelKey as never)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

interface LoopFieldsProps {
  data: LoopNodeData;
  onUpdate: (updates: Partial<LoopNodeData>) => void;
}

function LoopFields({ data, onUpdate }: LoopFieldsProps) {
  const { t } = useTranslation("automations");

  return (
    <div className="space-y-2">
      <Label htmlFor="loop-collection-field">{t("inspector.collectionField")}</Label>
      <Input
        id="loop-collection-field"
        value={data.collectionField}
        onChange={(e) => onUpdate({ collectionField: e.target.value })}
        placeholder={t("inspector.collectionFieldPlaceholder")}
      />
    </div>
  );
}
