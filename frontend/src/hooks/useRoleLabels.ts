import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getRoleLabelsApiV1SettingsRolesGet,
  getGetRoleLabelsApiV1SettingsRolesGetQueryKey,
  updateRoleLabelsApiV1SettingsRolesPut,
} from "@/api/generated/settings/settings";
import type { RoleLabelsResponse } from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

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

export const useUpdateRoleLabels = (
  options?: MutationOpts<RoleLabelsResponse, RoleLabelsResponse>
) => {
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (payload: RoleLabelsResponse) => {
      return updateRoleLabelsApiV1SettingsRolesPut(
        payload as Parameters<typeof updateRoleLabelsApiV1SettingsRolesPut>[0]
      ) as unknown as Promise<RoleLabelsResponse>;
    },
    onSuccess: (...args) => {
      qc.setQueryData(ROLE_LABELS_QUERY_KEY, args[0]);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

type RoleKey = keyof RoleLabelsResponse;

export const getRoleLabel = (role: RoleKey, labels?: RoleLabelsResponse) =>
  labels?.[role] ?? DEFAULT_ROLE_LABELS[role];
