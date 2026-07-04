import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { type InitiativeEnableFlag, TOGGLEABLE_TOOLS } from "@/lib/tools/registry";

export interface AdvancedToolsSectionProps {
  /** Current on/off state, keyed by the initiative feature flag. */
  enabled: Partial<Record<InitiativeEnableFlag, boolean>>;
  /** Called with the flag + its new value when a toggle changes. */
  onToggle: (flag: InitiativeEnableFlag, value: boolean) => void;
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

export const AdvancedToolsSection = ({
  enabled,
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
        const flag = tool.enableFlag as InitiativeEnableFlag;
        const toggle = tool.settingsToggle;
        if (!toggle) return null;
        // The advanced tool row only appears when the deployment configures one
        // at runtime, and it borrows that deployment's display name.
        const isAdvancedTool = tool.id === Tool.advanced_tool;
        if (isAdvancedTool && !advancedTool) return null;
        const title =
          isAdvancedTool && advancedTool ? advancedTool.name : t(toggle.titleKey as never);
        const description = isAdvancedTool
          ? t(toggle.descriptionKey as never, { name: advancedTool?.name ?? "" })
          : t(toggle.descriptionKey as never);
        return (
          <AdvancedToolToggle
            key={tool.id}
            id={`${idPrefix}-${tool.id}-toggle`}
            title={title}
            description={description}
            checked={enabled[flag] ?? false}
            onCheckedChange={(value) => onToggle(flag, value)}
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
