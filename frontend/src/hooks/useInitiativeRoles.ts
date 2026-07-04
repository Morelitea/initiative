import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  InitiativeRoleCreate,
  InitiativeRoleRead,
  InitiativeRoleUpdate,
  MyInitiativePermissions,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  createInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesPost,
  deleteInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdDelete,
  getGetMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGetQueryKey,
  getListInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGetQueryKey,
  getMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGet,
  listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet,
  updateInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdPatch,
} from "@/api/generated/initiatives/initiatives";
import { invalidateInitiativeRoles, invalidateMyPermissions } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  TOGGLEABLE_TOOLS,
  TOOL_REGISTRY,
  TOOLS,
  toolCamelPlural,
  toolCreatePermission,
  toolPascalSingular,
  toolViewPermission,
} from "@/lib/tools";

export const useInitiativeRoles = (initiativeId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRoleRead[]>({
    queryKey: getListInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGetQueryKey(
      guildId,
      initiativeId!
    ),
    queryFn: () =>
      listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet(
        guildId,
        initiativeId!
      ) as unknown as Promise<InitiativeRoleRead[]>,
    enabled: !!initiativeId,
    staleTime: 30 * 1000,
  });
};

export const useMyInitiativePermissions = (initiativeId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<MyInitiativePermissions>({
    queryKey:
      getGetMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGetQueryKey(
        guildId,
        initiativeId!
      ),
    queryFn: () =>
      getMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGet(
        guildId,
        initiativeId!
      ) as unknown as Promise<MyInitiativePermissions>,
    enabled: !!initiativeId,
    staleTime: 60 * 1000,
  });
};

export const useCreateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async (data: InitiativeRoleCreate) => {
      return createInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesPost(
        guildId,
        initiativeId,
        data
      ) as unknown as Promise<InitiativeRoleRead>;
    },
    onSuccess: () => {
      toast.success(t("settings.roleCreated"));
      void invalidateInitiativeRoles(initiativeId);
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleCreateError"));
    },
  });
};

export const useUpdateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async ({ roleId, data }: { roleId: number; data: InitiativeRoleUpdate }) => {
      return updateInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdPatch(
        guildId,
        initiativeId,
        roleId,
        data
      ) as unknown as Promise<InitiativeRoleRead>;
    },
    onSuccess: () => {
      toast.success(t("settings.roleUpdated"));
      void invalidateInitiativeRoles(initiativeId);
      void invalidateMyPermissions(initiativeId);
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleUpdateError"));
    },
  });
};

export const useDeleteRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async (roleId: number) => {
      await deleteInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdDelete(
        guildId,
        initiativeId,
        roleId
      );
    },
    onSuccess: () => {
      toast.success(t("settings.roleDeleted"));
      void invalidateInitiativeRoles(initiativeId);
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleDeleteError"));
    },
  });
};

// Helper to check if user has a specific permission
export const hasPermission = (
  permissions: MyInitiativePermissions | undefined,
  key: PermissionKey
): boolean => {
  if (!permissions) return false;
  // Managers always have all permissions
  if (permissions.is_manager) return true;
  return permissions.permissions[key] ?? false;
};

// Helper to check if a tool is visible to the user.
// Reads the permission value directly — the backend already accounts for
// initiative-level master switches and manager status, so we must not
// short-circuit on is_manager here.
export const isToolVisible = (
  permissions: MyInitiativePermissions | undefined,
  tool: Tool
): boolean => {
  if (!permissions) return false;
  return permissions.permissions[toolViewPermission(tool)] ?? false;
};

// Helper to check if the user can create a tool's content.
// Same as isToolVisible — reads the backend value directly.
export const canCreateTool = (
  permissions: MyInitiativePermissions | undefined,
  tool: Tool
): boolean => {
  if (!permissions) return false;
  return permissions.permissions[toolCreatePermission(tool)] ?? false;
};

// i18n-based permission label keys (use with t()) — one view/create pair per
// tool, derived: settings.permissions.view{PascalPlural} / create{PascalPlural}.
export const PERMISSION_LABEL_KEYS: Record<PermissionKey, string> = Object.fromEntries(
  TOOLS.flatMap((tool) => [
    [toolViewPermission(tool), `settings.permissions.view${toolPascalSingular(tool)}s`],
    [toolCreatePermission(tool), `settings.permissions.create${toolPascalSingular(tool)}s`],
  ])
) as Record<PermissionKey, string>;

// All permission keys in display order (view before create, per tool)
export const ALL_PERMISSION_KEYS: PermissionKey[] = TOOLS.flatMap((tool) => [
  toolViewPermission(tool),
  toolCreatePermission(tool),
]);

// Permission groups for card-based layout
export type PermissionGroup = {
  labelKey: string;
  keys: PermissionKey[];
};

const toolPermissionGroup = (tool: Tool): PermissionGroup => ({
  labelKey: `settings.permissionGroups.${toolCamelPlural(tool)}`,
  keys: [toolViewPermission(tool), toolCreatePermission(tool)],
});

// Core (always-on) tools' permissions, always visible
export const CORE_PERMISSION_GROUPS: PermissionGroup[] = TOOLS.filter(
  (tool) => TOOL_REGISTRY[tool].core
).map(toolPermissionGroup);

// Opt-in tools' permissions shown in accordion (the advanced tool is broken
// out separately because its whole group is runtime-config-gated)
export const ADVANCED_PERMISSION_GROUPS: PermissionGroup[] = TOGGLEABLE_TOOLS.filter(
  (tool) => tool !== Tool.advanced_tool
).map(toolPermissionGroup);

// Permission group for the optional embedded advanced tool. Only included
// in the role-permissions UI when the deployment has an advanced tool URL
// configured at runtime — see InitiativeSettingsRolesTab for the gating.
export const ADVANCED_TOOL_PERMISSION_GROUP: PermissionGroup = toolPermissionGroup(
  Tool.advanced_tool
);

// All groups combined (for backward compat)
export const PERMISSION_GROUPS: PermissionGroup[] = [
  ...CORE_PERMISSION_GROUPS,
  ...ADVANCED_PERMISSION_GROUPS,
];
