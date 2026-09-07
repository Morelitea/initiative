import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  TOGGLEABLE_TOOLS,
  toolCamelPlural,
  toolRouteSegment,
  toolViewPermission,
} from "@/lib/tools";

/**
 * The roles that can actually see a tool once its master switch is on.
 *
 * Manager roles see every tool whatever their stored permissions say, so they
 * are always in the list; every other role is in it only if its
 * `{plural}_enabled` permission is on. Exported because it is the fact the
 * whole screen turns on — a tool with no non-manager role behind it is on for
 * the manager reading the screen and off for everybody else.
 */
export const rolesThatCanView = (
  roles: InitiativeRoleRead[],
  tool: Tool
): { granted: InitiativeRoleRead[]; nonManagerGranted: InitiativeRoleRead[] } => {
  const key = toolViewPermission(tool);
  const granted = roles.filter((role) => role.is_manager || (role.permissions[key] ?? false));
  return { granted, nonManagerGranted: granted.filter((role) => !role.is_manager) };
};

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
  /**
   * The initiative's roles. When present, an enabled tool says who can see it —
   * absent on the create-initiative dialog, where no roles exist yet.
   */
  roles?: InitiativeRoleRead[];
  /** Open the roles screen. Rendered as a link beside the audience line. */
  onManageRoles?: () => void;
  /** Grant a tool's view permission to every non-manager role, in one step. */
  onGrantToEveryone?: (tool: Tool) => void;
}

interface AdvancedToolToggleProps {
  id: string;
  title: string;
  description: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  disabled: boolean;
  audience?: React.ReactNode;
}

const AdvancedToolToggle = ({
  id,
  title,
  description,
  checked,
  onCheckedChange,
  disabled,
  audience,
}: AdvancedToolToggleProps) => (
  <div className="space-y-2 rounded-md border p-3">
    <div className="flex items-center justify-between gap-4">
      <div className="space-y-0.5">
        <Label htmlFor={id}>{title}</Label>
        <p className="text-muted-foreground text-xs">{description}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
    </div>
    {audience}
  </div>
);

/**
 * Who can see this tool now that it is on — the half of the answer the master
 * switch alone never gave. A tool no ordinary role has been granted is on for
 * managers only, which is the state the switch used to leave behind silently,
 * so that case says so and offers the one-click grant.
 */
const ToolAudience = ({
  tool,
  roles,
  onManageRoles,
  onGrantToEveryone,
  disabled,
}: {
  tool: Tool;
  roles: InitiativeRoleRead[];
  onManageRoles?: () => void;
  onGrantToEveryone?: (tool: Tool) => void;
  disabled: boolean;
}) => {
  const { t } = useTranslation("initiatives");
  const { nonManagerGranted } = rolesThatCanView(roles, tool);
  const managersOnly = nonManagerGranted.length === 0;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-2 text-xs">
      {managersOnly ? (
        <span className="flex items-center gap-1.5 text-amber-600 dark:text-amber-500">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0" />
          {t("settings.toolAudience.managersOnly")}
        </span>
      ) : (
        <span className="text-muted-foreground">
          {t("settings.toolAudience.visibleTo", {
            roles: nonManagerGranted.map((role) => role.display_name).join(", "),
          })}
        </span>
      )}
      {managersOnly && onGrantToEveryone && (
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs"
          disabled={disabled}
          onClick={() => onGrantToEveryone(tool)}
        >
          {t("settings.toolAudience.grantToEveryone")}
        </Button>
      )}
      {onManageRoles && (
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-muted-foreground text-xs"
          onClick={onManageRoles}
        >
          {t("settings.toolAudience.manageRoles")}
        </Button>
      )}
    </div>
  );
};

/**
 * One master-switch row per toggleable tool, derived from the registry
 * (core tools are always on and never get a row).
 */
export const AdvancedToolsSection = ({
  values,
  onToggle,
  canManage,
  isSaving,
  layout = "card",
  idPrefix = "advanced-tools",
  roles,
  onManageRoles,
  onGrantToEveryone,
}: AdvancedToolsSectionProps) => {
  const { t } = useTranslation("initiatives");
  const disabled = !canManage || isSaving;

  const rows = (
    <div className="space-y-3">
      {TOGGLEABLE_TOOLS.map((tool) => {
        const camel = toolCamelPlural(tool);
        const enabled = values[tool] ?? false;
        return (
          <AdvancedToolToggle
            key={tool}
            id={`${idPrefix}-${toolRouteSegment(tool)}-toggle`}
            title={t(`${camel}Feature` as never)}
            description={t(`${camel}FeatureDescription` as never)}
            checked={enabled}
            onCheckedChange={(value) => onToggle(tool, value)}
            disabled={disabled}
            audience={
              enabled && roles ? (
                <ToolAudience
                  tool={tool}
                  roles={roles}
                  onManageRoles={onManageRoles}
                  onGrantToEveryone={onGrantToEveryone}
                  disabled={disabled}
                />
              ) : undefined
            }
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
