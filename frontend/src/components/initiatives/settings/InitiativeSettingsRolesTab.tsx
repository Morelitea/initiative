import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead, PermissionKey } from "@/api/generated/initiativeAPI.schemas";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { TabsContent } from "@/components/ui/tabs";
import { useAppConfig } from "@/hooks/useAppConfig";
import {
  ADVANCED_PERMISSION_GROUPS,
  ADVANCED_TOOL_PERMISSION_GROUP,
  CORE_PERMISSION_GROUPS,
  PERMISSION_LABEL_KEYS,
  type PermissionGroup,
  useDeleteRole,
  useInitiativeRoles,
  useUpdateRole,
} from "@/hooks/useInitiativeRoles";

interface InitiativeSettingsRolesTabProps {
  initiativeId: number;
  canManageMembers: boolean;
  // "Full access" (override_share_restrictions) is guild-admin-settable only —
  // a stricter gate than canManageMembers (which also includes PM managers), so
  // a PM can't grant its own role the share override (self-escalation).
  isGuildAdmin: boolean;
  onOpenCreateRoleDialog: () => void;
  onDeleteRole: (role: InitiativeRoleRead) => void;
  onRenameRole: (role: InitiativeRoleRead) => void;
}

const PermissionGroupSection = ({
  group,
  role,
  isPM,
  canManageMembers,
  isPending,
  onToggle,
  t,
}: {
  group: PermissionGroup;
  role: InitiativeRoleRead;
  isPM: boolean;
  canManageMembers: boolean;
  isPending: boolean;
  onToggle: (role: InitiativeRoleRead, key: PermissionKey, enabled: boolean) => void;
  t: (key: never) => string;
}) => (
  <div>
    <h4 className="mb-2 font-medium text-muted-foreground text-sm">{t(group.labelKey as never)}</h4>
    <div className="space-y-3">
      {group.keys.map((key) => (
        <div key={key} className="flex items-center justify-between">
          <Label className="font-normal">{t(PERMISSION_LABEL_KEYS[key] as never)}</Label>
          <Switch
            checked={isPM || (role.permissions[key] ?? false)}
            disabled={isPM || !canManageMembers || isPending}
            onCheckedChange={(checked) => onToggle(role, key, checked)}
          />
        </div>
      ))}
    </div>
  </div>
);

export const InitiativeSettingsRolesTab = ({
  initiativeId,
  canManageMembers,
  isGuildAdmin,
  onOpenCreateRoleDialog,
  onDeleteRole,
  onRenameRole,
}: InitiativeSettingsRolesTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  const rolesQuery = useInitiativeRoles(initiativeId || null);
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  // Only surface the advanced-tool permission group when the deployment has
  // an advanced tool URL configured. OSS deployments without it never see
  // these permission rows in role settings.
  const { advancedTool } = useAppConfig();
  const advancedGroups = advancedTool
    ? [...ADVANCED_PERMISSION_GROUPS, ADVANCED_TOOL_PERMISSION_GROUP]
    : ADVANCED_PERMISSION_GROUPS;

  const handleTogglePermission = useCallback(
    (role: InitiativeRoleRead, key: PermissionKey, enabled: boolean) => {
      if (role.name === "project_manager") return;
      const newPermissions = { ...role.permissions, [key]: enabled };
      updateRoleMutation.mutate({ roleId: role.id, data: { permissions: newPermissions } });
    },
    [updateRoleMutation]
  );

  const handleToggleFullAccess = useCallback(
    (role: InitiativeRoleRead, enabled: boolean) => {
      updateRoleMutation.mutate({
        roleId: role.id,
        data: { override_share_restrictions: enabled },
      });
    },
    [updateRoleMutation]
  );

  return (
    <TabsContent value="roles">
      <div className="space-y-4">
        <div>
          <h3 className="font-semibold text-lg">{t("settings.rolesTitle")}</h3>
          <p className="text-muted-foreground text-sm">{t("settings.rolesDescription")}</p>
        </div>

        {rolesQuery.isLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("settings.loadingRoles")}
          </div>
        ) : rolesQuery.data ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {rolesQuery.data.map((role) => {
              const isPM = role.name === "project_manager";
              return (
                <Card key={role.id}>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <CardTitle className="text-base">{role.display_name}</CardTitle>
                      {role.is_builtin && (
                        <Badge variant="secondary" className="text-xs">
                          {t("settings.builtIn")}
                        </Badge>
                      )}
                      {role.is_manager && (
                        <Badge variant="outline" className="text-xs">
                          {t("settings.manager")}
                        </Badge>
                      )}
                      {role.override_share_restrictions && (
                        <Badge className="text-xs">{t("settings.fullAccess")}</Badge>
                      )}
                      <Badge variant="outline" className="text-xs">
                        {t("settings.memberCountBadge", { count: role.member_count })}
                      </Badge>
                    </div>
                    {canManageMembers && (
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onRenameRole(role)}
                          disabled={updateRoleMutation.isPending}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        {!role.is_builtin && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => onDeleteRole(role)}
                            disabled={deleteRoleMutation.isPending || role.member_count > 0}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        )}
                      </div>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {isPM && isGuildAdmin && (
                      <div className="flex items-start justify-between gap-4 rounded-md border p-3">
                        <div className="space-y-1">
                          <Label className="font-medium">{t("settings.fullAccess")}</Label>
                          <p className="text-muted-foreground text-xs">
                            {t("settings.fullAccessDescription")}
                          </p>
                        </div>
                        <Switch
                          checked={role.override_share_restrictions}
                          disabled={updateRoleMutation.isPending}
                          onCheckedChange={(checked) => handleToggleFullAccess(role, checked)}
                        />
                      </div>
                    )}

                    {CORE_PERMISSION_GROUPS.map((group) => (
                      <PermissionGroupSection
                        key={group.labelKey}
                        group={group}
                        role={role}
                        isPM={isPM}
                        canManageMembers={canManageMembers}
                        isPending={updateRoleMutation.isPending}
                        onToggle={handleTogglePermission}
                        t={t as unknown as (key: never) => string}
                      />
                    ))}

                    {advancedGroups.length > 0 && (
                      <Accordion type="single" collapsible>
                        <AccordionItem value="advanced" className="border-b-0">
                          <AccordionTrigger className="py-2 font-medium text-muted-foreground text-sm">
                            {t("advancedTools")}
                          </AccordionTrigger>
                          <AccordionContent className="space-y-4 pt-2">
                            {advancedGroups.map((group) => (
                              <PermissionGroupSection
                                key={group.labelKey}
                                group={group}
                                role={role}
                                isPM={isPM}
                                canManageMembers={canManageMembers}
                                isPending={updateRoleMutation.isPending}
                                onToggle={handleTogglePermission}
                                t={t as unknown as (key: never) => string}
                              />
                            ))}
                          </AccordionContent>
                        </AccordionItem>
                      </Accordion>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        ) : null}

        {canManageMembers && (
          <Button variant="outline" onClick={onOpenCreateRoleDialog}>
            <Plus className="mr-2 h-4 w-4" />
            {t("settings.addCustomRole")}
          </Button>
        )}
      </div>
    </TabsContent>
  );
};
