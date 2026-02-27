import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listInitiativeRolesApiV1InitiativesInitiativeIdRolesGet,
  getListInitiativeRolesApiV1InitiativesInitiativeIdRolesGetQueryKey,
  createInitiativeRoleApiV1InitiativesInitiativeIdRolesPost,
  updateInitiativeRoleApiV1InitiativesInitiativeIdRolesRoleIdPatch,
  deleteInitiativeRoleApiV1InitiativesInitiativeIdRolesRoleIdDelete,
  getMyInitiativePermissionsApiV1InitiativesInitiativeIdMyPermissionsGet,
  getGetMyInitiativePermissionsApiV1InitiativesInitiativeIdMyPermissionsGetQueryKey,
} from "@/api/generated/initiatives/initiatives";
import { invalidateInitiativeRoles, invalidateMyPermissions } from "@/api/query-keys";
import type {
  InitiativeRoleCreate,
  InitiativeRoleRead,
  InitiativeRoleUpdate,
  MyInitiativePermissions,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";

export const useInitiativeRoles = (initiativeId: number | null) => {
  return useQuery<InitiativeRoleRead[]>({
    queryKey: getListInitiativeRolesApiV1InitiativesInitiativeIdRolesGetQueryKey(initiativeId!),
    queryFn: () =>
      listInitiativeRolesApiV1InitiativesInitiativeIdRolesGet(initiativeId!) as unknown as Promise<
        InitiativeRoleRead[]
      >,
    enabled: !!initiativeId,
    staleTime: 30 * 1000,
  });
};

export const useMyInitiativePermissions = (initiativeId: number | null) => {
  return useQuery<MyInitiativePermissions>({
    queryKey: getGetMyInitiativePermissionsApiV1InitiativesInitiativeIdMyPermissionsGetQueryKey(
      initiativeId!
    ),
    queryFn: () =>
      getMyInitiativePermissionsApiV1InitiativesInitiativeIdMyPermissionsGet(
        initiativeId!
      ) as unknown as Promise<MyInitiativePermissions>,
    enabled: !!initiativeId,
    staleTime: 60 * 1000,
  });
};

export const useCreateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");

  return useMutation({
    mutationFn: async (data: InitiativeRoleCreate) => {
      return createInitiativeRoleApiV1InitiativesInitiativeIdRolesPost(
        initiativeId,
        data
      ) as unknown as Promise<InitiativeRoleRead>;
    },
    onSuccess: () => {
      toast.success(t("settings.roleCreated"));
      void invalidateInitiativeRoles(initiativeId);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.roleCreateError");
      toast.error(message);
    },
  });
};

export const useUpdateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");

  return useMutation({
    mutationFn: async ({ roleId, data }: { roleId: number; data: InitiativeRoleUpdate }) => {
      return updateInitiativeRoleApiV1InitiativesInitiativeIdRolesRoleIdPatch(
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
      const message = error instanceof Error ? error.message : t("settings.roleUpdateError");
      toast.error(message);
    },
  });
};

export const useDeleteRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");

  return useMutation({
    mutationFn: async (roleId: number) => {
      await deleteInitiativeRoleApiV1InitiativesInitiativeIdRolesRoleIdDelete(initiativeId, roleId);
    },
    onSuccess: () => {
      toast.success(t("settings.roleDeleted"));
      void invalidateInitiativeRoles(initiativeId);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.roleDeleteError");
      toast.error(message);
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

// Helper to check if a feature is enabled for the user
export const isFeatureEnabled = (
  permissions: MyInitiativePermissions | undefined,
  feature: "docs" | "projects" | "queues"
): boolean => {
  const keyMap: Record<typeof feature, PermissionKey> = {
    docs: "docs_enabled",
    projects: "projects_enabled",
    queues: "queues_enabled",
  };
  return hasPermission(permissions, keyMap[feature]);
};

// Helper to check if user can create (docs, projects, or queues)
export const canCreate = (
  permissions: MyInitiativePermissions | undefined,
  entity: "docs" | "projects" | "queues"
): boolean => {
  const keyMap: Record<typeof entity, PermissionKey> = {
    docs: "create_docs",
    projects: "create_projects",
    queues: "create_queues",
  };
  return hasPermission(permissions, keyMap[entity]);
};

// Permission key labels for display (hardcoded, kept for backward compat)
export const PERMISSION_LABELS: Record<PermissionKey, string> = {
  docs_enabled: "View Documents",
  projects_enabled: "View Projects",
  create_docs: "Create Documents",
  create_projects: "Create Projects",
  queues_enabled: "View Queues",
  create_queues: "Create Queues",
};

// i18n-based permission label keys (use with t())
export const PERMISSION_LABEL_KEYS: Record<PermissionKey, string> = {
  docs_enabled: "settings.permissions.viewDocuments",
  projects_enabled: "settings.permissions.viewProjects",
  create_docs: "settings.permissions.createDocuments",
  create_projects: "settings.permissions.createProjects",
  queues_enabled: "settings.permissions.viewQueues",
  create_queues: "settings.permissions.createQueues",
};

// All permission keys in display order
export const ALL_PERMISSION_KEYS: PermissionKey[] = [
  "docs_enabled",
  "create_docs",
  "projects_enabled",
  "create_projects",
  "queues_enabled",
  "create_queues",
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
];

// All groups combined (for backward compat)
export const PERMISSION_GROUPS: PermissionGroup[] = [
  ...CORE_PERMISSION_GROUPS,
  ...ADVANCED_PERMISSION_GROUPS,
];
