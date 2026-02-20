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
} from "@/api/generated/initiativeAPI.schemas";
import type { PermissionKey } from "@/types/api";

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
  feature: "docs" | "projects"
): boolean => {
  const key: PermissionKey = feature === "docs" ? "docs_enabled" : "projects_enabled";
  return hasPermission(permissions, key);
};

// Helper to check if user can create (docs or projects)
export const canCreate = (
  permissions: MyInitiativePermissions | undefined,
  entity: "docs" | "projects"
): boolean => {
  const key: PermissionKey = entity === "docs" ? "create_docs" : "create_projects";
  return hasPermission(permissions, key);
};

// Permission key labels for display
export const PERMISSION_LABELS: Record<PermissionKey, string> = {
  docs_enabled: "View Documents",
  projects_enabled: "View Projects",
  create_docs: "Create Documents",
  create_projects: "Create Projects",
};

// All permission keys in display order
export const ALL_PERMISSION_KEYS: PermissionKey[] = [
  "docs_enabled",
  "projects_enabled",
  "create_docs",
  "create_projects",
];
