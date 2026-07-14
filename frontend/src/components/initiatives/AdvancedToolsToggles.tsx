import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import {
  TOGGLEABLE_TOOLS,
  toolAvailable,
  toolCamelPlural,
  toolDisplayName,
  toolRouteSegment,
} from "@/lib/tools";

export interface AdvancedToolsSectionProps {
  /** Current master-switch value per toggleable tool. */
  values: Record<Tool, boolean> | Partial<Record<Tool, boolean>>;
  /** Toggle one tool's master switch. */
  onToggle: (tool: Tool, value: boolean) => void;
  canManage: boolean;
  isSaving: boolean;
  /** "card" wraps the rows in a Card with title+description (settings page). "plain" returns just the rows (for use inside an Accordion). */
  layout?: "card" | "plain";
  /** Optional prefix for input IDs so multiple instances don't collide. */
  idPrefix?: string;
}

interface AdvancedToolToggleProps {
  id: string;
  title: string;
  description: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  disabled: boolean;
}

const AdvancedToolToggle = ({
  id,
  title,
  description,
  checked,
  onCheckedChange,
  disabled,
}: AdvancedToolToggleProps) => (
  <div className="flex items-center justify-between gap-4 rounded-md border p-3">
    <div className="space-y-0.5">
      <Label htmlFor={id}>{title}</Label>
      <p className="text-muted-foreground text-xs">{description}</p>
    </div>
    <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
  </div>
);

/**
 * One master-switch row per toggleable tool, derived from the registry
 * (core tools are always on and never get a row). The advanced tool renders
 * under the deployment's own name for it and only when the runtime config
 * exposes one.
 */
export const AdvancedToolsSection = ({
  values,
  onToggle,
  canManage,
  isSaving,
  layout = "card",
  idPrefix = "advanced-tools",
}: AdvancedToolsSectionProps) => {
  const { t } = useTranslation("initiatives");
  const { advancedTool } = useAppConfig();
  const disabled = !canManage || isSaving;

  const rows = (
    <div className="space-y-3">
      {TOGGLEABLE_TOOLS.map((tool) => {
        if (!toolAvailable(tool, advancedTool)) return null;
        const camel = toolCamelPlural(tool);
        const title = toolDisplayName(tool, t(`${camel}Feature` as never), advancedTool);
        return (
          <AdvancedToolToggle
            key={tool}
            id={`${idPrefix}-${toolRouteSegment(tool)}-toggle`}
            title={title}
            description={t(`${camel}FeatureDescription` as never, {
              name: advancedTool?.name ?? "",
            })}
            checked={values[tool] ?? false}
            onCheckedChange={(value) => onToggle(tool, value)}
            disabled={disabled}
          />
        );
      })}
    </div>
  );

  if (layout === "plain") return rows;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{t("advancedTools")}</CardTitle>
        <CardDescription>{t("advancedToolsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>{rows}</CardContent>
    </Card>
  );
};
