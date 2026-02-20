import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getRoleLabelsApiV1SettingsRolesGet,
  getGetRoleLabelsApiV1SettingsRolesGetQueryKey,
  updateRoleLabelsApiV1SettingsRolesPut,
} from "@/api/generated/settings/settings";
import type { RoleLabelsResponse } from "@/api/generated/initiativeAPI.schemas";

export const DEFAULT_ROLE_LABELS: RoleLabelsResponse = {
  admin: "Admin",
  project_manager: "Project manager",
  member: "Member",
};

export const ROLE_LABELS_QUERY_KEY = getGetRoleLabelsApiV1SettingsRolesGetQueryKey();

export const useRoleLabels = () =>
  useQuery({
    queryKey: ROLE_LABELS_QUERY_KEY,
    queryFn: () => getRoleLabelsApiV1SettingsRolesGet() as unknown as Promise<RoleLabelsResponse>,
    placeholderData: DEFAULT_ROLE_LABELS,
    staleTime: Infinity,
  });

export const useUpdateRoleLabels = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RoleLabelsResponse) => {
      return updateRoleLabelsApiV1SettingsRolesPut(
        payload as Parameters<typeof updateRoleLabelsApiV1SettingsRolesPut>[0]
      ) as unknown as Promise<RoleLabelsResponse>;
    },
    onSuccess: (data) => {
      qc.setQueryData(ROLE_LABELS_QUERY_KEY, data);
    },
  });
};

type RoleKey = keyof RoleLabelsResponse;

export const getRoleLabel = (role: RoleKey, labels?: RoleLabelsResponse) =>
  labels?.[role] ?? DEFAULT_ROLE_LABELS[role];
