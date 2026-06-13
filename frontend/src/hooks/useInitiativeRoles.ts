import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  InitiativeRoleCreate,
  InitiativeRoleRead,
  InitiativeRoleUpdate,
  MyInitiativePermissions,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";
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

// Helper to check if a feature is enabled for the user.
// Reads the permission value directly — the backend already accounts for
// initiative-level flags and manager status, so we must not short-circuit
// on is_manager here.
export const isFeatureEnabled = (
  permissions: MyInitiativePermissions | undefined,
  feature: "docs" | "projects" | "queues" | "events" | "counters"
): boolean => {
  if (!permissions) return false;
  const keyMap: Record<typeof feature, PermissionKey> = {
    docs: "docs_enabled",
    projects: "projects_enabled",
    queues: "queues_enabled",
    events: "events_enabled",
    counters: "counters_enabled",
  };
  return permissions.permissions[keyMap[feature]] ?? false;
};

// Helper to check if user can create (docs, projects, queues, or events).
// Same as isFeatureEnabled — reads backend value directly.
export const canCreate = (
  permissions: MyInitiativePermissions | undefined,
  entity: "docs" | "projects" | "queues" | "events" | "counters"
): boolean => {
  if (!permissions) return false;
  const keyMap: Record<typeof entity, PermissionKey> = {
    docs: "create_docs",
    projects: "create_projects",
    queues: "create_queues",
    events: "create_events",
    counters: "create_counters",
  };
  return permissions.permissions[keyMap[entity]] ?? false;
};

// Permission key labels for display (hardcoded, kept for backward compat)
export const PERMISSION_LABELS: Record<PermissionKey, string> = {
  docs_enabled: "View Documents",
  projects_enabled: "View Projects",
  create_docs: "Create Documents",
  create_projects: "Create Projects",
  queues_enabled: "View Queues",
  create_queues: "Create Queues",
  events_enabled: "View Events",
  create_events: "Create Events",
  advanced_tool_enabled: "View Advanced Tool",
  create_advanced_tool: "Create in Advanced Tool",
  counters_enabled: "View Counters",
  create_counters: "Create Counters",
};

// i18n-based permission label keys (use with t())
export const PERMISSION_LABEL_KEYS: Record<PermissionKey, string> = {
  docs_enabled: "settings.permissions.viewDocuments",
  projects_enabled: "settings.permissions.viewProjects",
  create_docs: "settings.permissions.createDocuments",
  create_projects: "settings.permissions.createProjects",
  queues_enabled: "settings.permissions.viewQueues",
  create_queues: "settings.permissions.createQueues",
  events_enabled: "settings.permissions.viewEvents",
  create_events: "settings.permissions.createEvents",
  advanced_tool_enabled: "settings.permissions.viewAdvancedTool",
  create_advanced_tool: "settings.permissions.createAdvancedTool",
  counters_enabled: "settings.permissions.viewCounters",
  create_counters: "settings.permissions.createCounters",
};

// All permission keys in display order
export const ALL_PERMISSION_KEYS: PermissionKey[] = [
  "docs_enabled",
  "create_docs",
  "projects_enabled",
  "create_projects",
  "queues_enabled",
  "create_queues",
  "events_enabled",
  "create_events",
  "advanced_tool_enabled",
  "create_advanced_tool",
  "counters_enabled",
  "create_counters",
];

// Permission groups for card-based layout
export type PermissionGroup = {
  labelKey: string;
  keys: PermissionKey[];
};

// Core permissions always visible
export const CORE_PERMISSION_GROUPS: PermissionGroup[] = [
  { labelKey: "settings.permissionGroups.documents", keys: ["docs_enabled", "create_docs"] },
  { labelKey: "settings.permissionGroups.projects", keys: ["projects_enabled", "create_projects"] },
];

// Advanced tools permissions shown in accordion
export const ADVANCED_PERMISSION_GROUPS: PermissionGroup[] = [
  { labelKey: "settings.permissionGroups.queues", keys: ["queues_enabled", "create_queues"] },
  { labelKey: "settings.permissionGroups.events", keys: ["events_enabled", "create_events"] },
  {
    labelKey: "settings.permissionGroups.counters",
    keys: ["counters_enabled", "create_counters"],
  },
];

// Permission group for the optional embedded advanced tool. Only included
// in the role-permissions UI when the deployment has an advanced tool URL
// configured at runtime — see InitiativeSettingsRolesTab for the gating.
export const ADVANCED_TOOL_PERMISSION_GROUP: PermissionGroup = {
  labelKey: "settings.permissionGroups.advancedTool",
  keys: ["advanced_tool_enabled", "create_advanced_tool"],
};

// All groups combined (for backward compat)
export const PERMISSION_GROUPS: PermissionGroup[] = [
  ...CORE_PERMISSION_GROUPS,
  ...ADVANCED_PERMISSION_GROUPS,
];
