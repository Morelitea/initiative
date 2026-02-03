import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import type {
  InitiativeRoleCreate,
  InitiativeRoleRead,
  InitiativeRoleUpdate,
  MyInitiativePermissions,
  PermissionKey,
} from "@/types/api";

const INITIATIVE_ROLES_KEY = "initiative-roles";
const MY_PERMISSIONS_KEY = "my-permissions";

export const useInitiativeRoles = (initiativeId: number | null) => {
  return useQuery<InitiativeRoleRead[]>({
    queryKey: [INITIATIVE_ROLES_KEY, initiativeId],
    queryFn: async () => {
      const response = await apiClient.get<InitiativeRoleRead[]>(
        `/initiatives/${initiativeId}/roles`
      );
      return response.data;
    },
    enabled: !!initiativeId,
    staleTime: 30 * 1000, // 30 seconds
  });
};

export const useMyInitiativePermissions = (initiativeId: number | null) => {
  return useQuery<MyInitiativePermissions>({
    queryKey: [MY_PERMISSIONS_KEY, initiativeId],
    queryFn: async () => {
      const response = await apiClient.get<MyInitiativePermissions>(
        `/initiatives/${initiativeId}/my-permissions`
      );
      return response.data;
    },
    enabled: !!initiativeId,
    staleTime: 60 * 1000, // 1 minute
  });
};

export const useCreateRole = (initiativeId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: InitiativeRoleCreate) => {
      const response = await apiClient.post<InitiativeRoleRead>(
        `/initiatives/${initiativeId}/roles`,
        data
      );
      return response.data;
    },
    onSuccess: () => {
      toast.success("Role created.");
      void queryClient.invalidateQueries({
        queryKey: [INITIATIVE_ROLES_KEY, initiativeId],
      });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to create role.";
      toast.error(message);
    },
  });
};

export const useUpdateRole = (initiativeId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ roleId, data }: { roleId: number; data: InitiativeRoleUpdate }) => {
      const response = await apiClient.patch<InitiativeRoleRead>(
        `/initiatives/${initiativeId}/roles/${roleId}`,
        data
      );
      return response.data;
    },
    onSuccess: () => {
      toast.success("Role updated.");
      void queryClient.invalidateQueries({
        queryKey: [INITIATIVE_ROLES_KEY, initiativeId],
      });
      // Also invalidate permissions in case they changed
      void queryClient.invalidateQueries({
        queryKey: [MY_PERMISSIONS_KEY, initiativeId],
      });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to update role.";
      toast.error(message);
    },
  });
};

export const useDeleteRole = (initiativeId: number) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (roleId: number) => {
      await apiClient.delete(`/initiatives/${initiativeId}/roles/${roleId}`);
    },
    onSuccess: () => {
      toast.success("Role deleted.");
      void queryClient.invalidateQueries({
        queryKey: [INITIATIVE_ROLES_KEY, initiativeId],
      });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to delete role.";
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
