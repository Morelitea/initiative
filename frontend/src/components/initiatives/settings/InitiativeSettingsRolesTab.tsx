import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { TabsContent } from "@/components/ui/tabs";
import type { InitiativeRoleRead, PermissionKey } from "@/api/generated/initiativeAPI.schemas";
import {
  useInitiativeRoles,
  useUpdateRole,
  useDeleteRole,
  CORE_PERMISSION_GROUPS,
  ADVANCED_PERMISSION_GROUPS,
  PERMISSION_LABEL_KEYS,
  type PermissionGroup,
} from "@/hooks/useInitiativeRoles";

interface InitiativeSettingsRolesTabProps {
  initiativeId: number;
  canManageMembers: boolean;
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
    <h4 className="text-muted-foreground mb-2 text-sm font-medium">{t(group.labelKey as never)}</h4>
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
  onOpenCreateRoleDialog,
  onDeleteRole,
  onRenameRole,
}: InitiativeSettingsRolesTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  const rolesQuery = useInitiativeRoles(initiativeId || null);
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  const handleTogglePermission = useCallback(
    (role: InitiativeRoleRead, key: PermissionKey, enabled: boolean) => {
      if (role.name === "project_manager") return;
      const newPermissions = { ...role.permissions, [key]: enabled };
      updateRoleMutation.mutate({ roleId: role.id, data: { permissions: newPermissions } });
    },
    [updateRoleMutation]
  );

  return (
    <TabsContent value="roles">
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-semibold">{t("settings.rolesTitle")}</h3>
          <p className="text-muted-foreground text-sm">{t("settings.rolesDescription")}</p>
        </div>

        {rolesQuery.isLoading ? (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
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
                      <Badge variant="outline" className="text-xs">
                        {t("settings.memberCountBadge", { count: role.member_count })}
                      </Badge>
                    </div>
                    {canManageMembers && !role.is_builtin && (
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onRenameRole(role)}
                          disabled={updateRoleMutation.isPending}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onDeleteRole(role)}
                          disabled={deleteRoleMutation.isPending || role.member_count > 0}
                        >
                          <Trash2 className="text-destructive h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-4">
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

                    {ADVANCED_PERMISSION_GROUPS.length > 0 && (
                      <Accordion type="single" collapsible>
                        <AccordionItem value="advanced" className="border-b-0">
                          <AccordionTrigger className="text-muted-foreground py-2 text-sm font-medium">
                            {t("advancedTools")}
                          </AccordionTrigger>
                          <AccordionContent className="space-y-4 pt-2">
                            {ADVANCED_PERMISSION_GROUPS.map((group) => (
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
